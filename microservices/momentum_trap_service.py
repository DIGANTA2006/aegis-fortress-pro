from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Iterable

from core.events.order_request_event import OrderRequestEvent
from execution.order_event_codec import OrderEventCodec
from microservices.base_service import BaseService
from models.order import OrderSide, OrderType
from models.signal import TradeSignal
from strategies.momentum_trap import MomentumTrapAnalyzer, MomentumTrapConfig


log = logging.getLogger(__name__)


class MomentumTrapService(BaseService):
    """Periodic 15m OHLCV scanner adapted from the original Aegis Fortress idea."""

    def __init__(
        self,
        event_bus,
        exchange_manager,
        ledger,
        kill_switch,
        market_state_store,
        symbols: Iterable[str],
        target_notional: float,
        max_position_notional: float,
        min_order_notional: float,
        order_type: str,
    ) -> None:
        super().__init__("momentum-trap-service")

        self.event_bus = event_bus
        self.exchange_manager = exchange_manager
        self.ledger = ledger
        self.kill_switch = kill_switch
        self.market_state_store = market_state_store
        self.symbols = tuple(self._env_symbols("AEGIS_MOMENTUM_TRAP_SYMBOLS", tuple(symbols)))
        self.target_notional = max(min_order_notional, min(target_notional, max_position_notional))
        self.min_order_notional = min_order_notional
        self.order_type = OrderType(str(order_type).upper())
        self.codec = OrderEventCodec()

        self.enabled = self._bool_env("AEGIS_MOMENTUM_TRAP_ENABLED", False)
        self.scan_interval_seconds = self._float_env("AEGIS_MOMENTUM_TRAP_INTERVAL_SECONDS", 60.0)
        self.timeframe = os.getenv("AEGIS_MOMENTUM_TRAP_TIMEFRAME", "15m").strip() or "15m"
        self.candle_limit = max(40, self._int_env("AEGIS_MOMENTUM_TRAP_CANDLE_LIMIT", 90))
        self.cooldown_seconds = self._float_env("AEGIS_MOMENTUM_TRAP_COOLDOWN_SECONDS", 1800.0)
        self.max_spread_bps = self._float_env("AEGIS_MOMENTUM_TRAP_MAX_SPREAD_BPS", 20.0)
        self.require_fresh_mark_price = self._bool_env("AEGIS_MOMENTUM_TRAP_REQUIRE_MARK_PRICE", False)
        self.symbol_blocklist = {
            item.upper()
            for item in self._env_symbols("AEGIS_SYMBOL_BLOCKLIST", ())
        }

        self.analyzer = MomentumTrapAnalyzer(
            MomentumTrapConfig(
                min_volume_multiplier=self._float_env("AEGIS_MOMENTUM_TRAP_MIN_VOLUME_MULT", 1.5),
                min_wick_body_ratio=self._float_env("AEGIS_MOMENTUM_TRAP_MIN_WICK_BODY_RATIO", 1.2),
                rsi_max=self._float_env("AEGIS_MOMENTUM_TRAP_RSI_MAX", 68.0),
                pullback_tolerance_bps=self._float_env("AEGIS_MOMENTUM_TRAP_PULLBACK_TOLERANCE_BPS", 85.0),
            )
        )

        self._last_signal_at: dict[str, float] = {}
        self._processed_signal_keys: set[str] = set()

        self.scans_completed = 0
        self.scan_errors = 0
        self.signals_published = 0
        self.skipped_existing_position = 0
        self.skipped_cooldown = 0
        self.skipped_blocklist = 0
        self.skipped_spread = 0

    async def on_start(self) -> None:
        if not self.enabled:
            log.info("Momentum trap service disabled. Set AEGIS_MOMENTUM_TRAP_ENABLED=true to enable it.")
            return

        log.info(
            "Momentum trap scanner enabled: symbols=%s timeframe=%s interval=%.1fs target_notional=%.2f",
            ", ".join(self.symbols),
            self.timeframe,
            self.scan_interval_seconds,
            self.target_notional,
        )

    async def run(self) -> None:
        while self.running:
            self.heartbeat()

            if not self.enabled:
                await asyncio.sleep(5.0)
                continue

            for symbol in self.symbols:
                if not self.running:
                    break

                await self._scan_symbol(symbol)
                await asyncio.sleep(0)

            self.scans_completed += 1
            await asyncio.sleep(self.scan_interval_seconds)

    async def _scan_symbol(self, symbol: str) -> None:
        normalized_symbol = symbol.upper()

        if normalized_symbol in self.symbol_blocklist:
            self.skipped_blocklist += 1
            return

        if not self.kill_switch.is_active():
            return

        position = self.ledger.get_position(symbol)
        if position is not None and abs(float(getattr(position, "quantity", 0.0) or 0.0)) > 0:
            self.skipped_existing_position += 1
            return

        if self._on_cooldown(symbol):
            self.skipped_cooldown += 1
            return

        if self.require_fresh_mark_price and symbol not in self.market_state_store.mark_prices():
            return

        if self._spread_too_wide(symbol):
            self.skipped_spread += 1
            return

        exchange = self._ohlcv_exchange()
        if exchange is None:
            self.scan_errors += 1
            log.warning("Momentum trap scanner has no exchange available for OHLCV")
            return

        try:
            ohlcv = await asyncio.to_thread(
                exchange.fetch_ohlcv,
                symbol,
                self.timeframe,
                limit=self.candle_limit,
            )

            decision = self.analyzer.analyze(symbol, ohlcv)

            if not decision.should_buy:
                return

            if decision.signal_key and decision.signal_key in self._processed_signal_keys:
                return

            await self._publish_buy_signal(decision)

            if decision.signal_key:
                self._processed_signal_keys.add(decision.signal_key)

            self._last_signal_at[symbol] = time.monotonic()
            self.signals_published += 1

        except Exception as exc:
            self.scan_errors += 1
            log.warning("Momentum trap scan failed for %s: %s", symbol, exc)

    async def _publish_buy_signal(self, decision) -> None:
        quantity = round(self.target_notional / max(decision.reference_price, 1e-12), 8)

        signal = TradeSignal(
            symbol=decision.symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            order_type=self.order_type,
            price=None,
            strategy_id="momentum_trap_fortress",
            reason=(
                f"{decision.reason}: close={decision.reference_price:.8f}, "
                f"confidence={decision.confidence:.2f}"
            ),
            confidence=decision.confidence,
        )

        order = signal.to_order()

        await self.event_bus.publish(
            OrderRequestEvent(
                event_type="ORDER_REQUEST",
                correlation_id=order.correlation_id,
                order_payload=self.codec.encode(order),
                mark_prices=self.market_state_store.mark_prices(),
            )
        )

        log.info(
            "Momentum trap published BUY request symbol=%s notional=%.2f confidence=%.2f reason=%s",
            decision.symbol,
            self.target_notional,
            decision.confidence,
            decision.reason,
        )

    def _ohlcv_exchange(self):
        primary = getattr(self.exchange_manager, "primary", None)
        if primary is not None:
            return primary

        exchanges = getattr(self.exchange_manager, "exchanges", {}) or {}
        return next(iter(exchanges.values()), None)

    def _spread_too_wide(self, symbol: str) -> bool:
        snapshots = self.market_state_store.snapshot().get("orderbooks", {})
        best_spread = None

        for key, orderbook in snapshots.items():
            if not key.endswith(f":{symbol}"):
                continue

            mid = float(orderbook.get("mid_price", 0.0) or 0.0)
            spread = float(orderbook.get("spread", 0.0) or 0.0)
            if mid <= 0 or spread < 0:
                continue

            spread_bps = (spread / mid) * 10_000.0
            best_spread = spread_bps if best_spread is None else min(best_spread, spread_bps)

        return best_spread is not None and best_spread > self.max_spread_bps

    def _on_cooldown(self, symbol: str) -> bool:
        last = self._last_signal_at.get(symbol)
        if last is None:
            return False
        return time.monotonic() - last < self.cooldown_seconds

    @staticmethod
    def _env_symbols(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        return tuple(item.strip() for item in raw.split(",") if item.strip())

    @staticmethod
    def _bool_env(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return float(default)
        try:
            return float(raw)
        except ValueError:
            return float(default)

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return int(default)
        try:
            return int(float(raw))
        except ValueError:
            return int(default)

    def metrics(self) -> dict:
        return {
            "enabled": self.enabled,
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "scans_completed": self.scans_completed,
            "scan_errors": self.scan_errors,
            "signals_published": self.signals_published,
            "skipped_existing_position": self.skipped_existing_position,
            "skipped_cooldown": self.skipped_cooldown,
            "skipped_blocklist": self.skipped_blocklist,
            "skipped_spread": self.skipped_spread,
            "processed_signal_keys": len(self._processed_signal_keys),
        }

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = self.metrics()
        return payload
