import logging
import os
import time
from collections import deque
from statistics import mean, pstdev

from models.order import OrderSide, OrderType
from models.signal import TradeSignal


log = logging.getLogger(__name__)


class MeanReversionImbalanceStrategy:
    """
    Conservative live strategy using:
    - rolling mid-price z-score
    - order book imbalance confirmation
    - spread quality filter
    - cooldown throttling
    - minimum exchange-sized orders for small accounts
    - take-profit, stop-loss, time-stop, and symbol cooldown recycling
    """

    def __init__(
        self,
        ledger,
        kill_switch,
        target_notional: float,
        max_position_notional: float,
        rolling_window: int,
        min_observations: int,
        entry_zscore: float,
        exit_zscore: float,
        imbalance_threshold: float,
        max_spread_bps: float,
        cooldown_seconds: float,
        order_type: str = "MARKET",
        min_order_notional: float = 0.0,
        take_profit_bps: float = 60.0,
        stop_loss_bps: float = 35.0,
        min_profit_after_fee_bps: float = 18.0,
        max_hold_seconds: float = 900.0,
        cooldown_after_exit_seconds: float = 900.0,
        loss_cooldown_seconds: float = 3600.0,
        bad_symbol_drop_bps: float = 1200.0,
    ) -> None:
        if target_notional <= 0:
            raise ValueError("target_notional must be positive")

        if max_position_notional <= 0:
            raise ValueError("max_position_notional must be positive")

        if min_order_notional < 0:
            raise ValueError("min_order_notional cannot be negative")

        if max_position_notional < min_order_notional:
            raise ValueError("max_position_notional must cover min_order_notional")

        if rolling_window < 5:
            raise ValueError("rolling_window must be at least 5")

        if min_observations < 5:
            raise ValueError("min_observations must be at least 5")

        if min_observations > rolling_window:
            raise ValueError("min_observations cannot exceed rolling_window")

        if entry_zscore <= 0:
            raise ValueError("entry_zscore must be positive")

        if exit_zscore < 0:
            raise ValueError("exit_zscore cannot be negative")

        if exit_zscore >= entry_zscore:
            raise ValueError("exit_zscore must be smaller than entry_zscore")

        if not 0 < imbalance_threshold <= 1:
            raise ValueError("imbalance_threshold must be in (0, 1]")

        if max_spread_bps <= 0:
            raise ValueError("max_spread_bps must be positive")

        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")

        if take_profit_bps <= 0:
            raise ValueError("take_profit_bps must be positive")

        if stop_loss_bps <= 0:
            raise ValueError("stop_loss_bps must be positive")

        if min_profit_after_fee_bps < 0:
            raise ValueError("min_profit_after_fee_bps cannot be negative")

        if max_hold_seconds < 0:
            raise ValueError("max_hold_seconds cannot be negative")

        if cooldown_after_exit_seconds < 0:
            raise ValueError("cooldown_after_exit_seconds cannot be negative")

        if loss_cooldown_seconds < 0:
            raise ValueError("loss_cooldown_seconds cannot be negative")

        if bad_symbol_drop_bps < 0:
            raise ValueError("bad_symbol_drop_bps cannot be negative")

        normalized_order_type = str(order_type).upper()

        if normalized_order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("order_type must be MARKET or LIMIT")

        self.ledger = ledger
        self.kill_switch = kill_switch

        self.target_notional = target_notional
        self.max_position_notional = max_position_notional
        self.min_order_notional = min_order_notional
        self.rolling_window = rolling_window
        self.min_observations = min_observations
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore
        self.imbalance_threshold = imbalance_threshold
        self.max_spread_bps = max_spread_bps
        self.cooldown_seconds = cooldown_seconds
        self.order_type = OrderType(normalized_order_type)
        self.take_profit_bps = take_profit_bps
        self.stop_loss_bps = stop_loss_bps
        self.min_profit_after_fee_bps = min_profit_after_fee_bps
        self.max_hold_seconds = max_hold_seconds
        self.cooldown_after_exit_seconds = cooldown_after_exit_seconds
        self.loss_cooldown_seconds = loss_cooldown_seconds
        self.bad_symbol_drop_bps = bad_symbol_drop_bps

        # Phase 3A hardening knobs. Defaults preserve old test behaviour;
        # production values are enabled through .env.
        self.taker_fee_bps = self._float_env("AEGIS_STRATEGY_TAKER_FEE_BPS", 0.0)
        self.slippage_bps = self._float_env("AEGIS_STRATEGY_SLIPPAGE_BPS", 0.0)
        self.expected_edge_multiplier = self._float_env(
            "AEGIS_STRATEGY_EXPECTED_EDGE_MULTIPLIER", 1.0
        )
        self.round_trip_cost_bps = max(
            0.0,
            (self.taker_fee_bps * 2.0) + self.slippage_bps,
        )
        self.required_min_profit_bps = max(
            self.min_profit_after_fee_bps,
            self.round_trip_cost_bps + self._float_env(
                "AEGIS_STRATEGY_PROFIT_BUFFER_BPS", 0.0
            ),
        )
        self.required_expected_edge_bps = max(
            self.required_min_profit_bps,
            self.round_trip_cost_bps * self.expected_edge_multiplier,
        )

        self.imbalance_confirm_snapshots = max(
            1,
            self._int_env("AEGIS_STRATEGY_IMBALANCE_CONFIRM_SNAPSHOTS", 1),
        )
        self.dynamic_stop_enabled = self._bool_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_ENABLED", False
        )
        self.dynamic_stop_min_bps = self._float_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_MIN_BPS", self.stop_loss_bps
        )
        self.dynamic_stop_max_bps = self._float_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_MAX_BPS", self.stop_loss_bps
        )
        self.dynamic_stop_multiplier = self._float_env(
            "AEGIS_STRATEGY_DYNAMIC_STOP_MULTIPLIER", 1.5
        )
        self.dynamic_stop_lookback = max(
            5,
            self._int_env("AEGIS_STRATEGY_DYNAMIC_STOP_LOOKBACK", 20),
        )

        self.btc_filter_enabled = self._bool_env("AEGIS_BTC_FILTER_ENABLED", False)
        self.btc_filter_require_data = self._bool_env(
            "AEGIS_BTC_FILTER_REQUIRE_DATA", False
        )
        self.btc_symbol = os.getenv("AEGIS_BTC_FILTER_SYMBOL", "BTC/USDT").strip() or "BTC/USDT"
        self.trade_btc_symbol = self._bool_env("AEGIS_TRADE_BTC_SYMBOL", True)
        self.btc_min_observations = max(
            5,
            self._int_env("AEGIS_BTC_FILTER_MIN_OBSERVATIONS", 10),
        )
        self.btc_danger_drop_bps = self._float_env(
            "AEGIS_BTC_FILTER_DANGER_DROP_BPS", 40.0
        )
        self.btc_volatility_max_bps = self._float_env(
            "AEGIS_BTC_FILTER_MAX_VOLATILITY_BPS", 80.0
        )

        self._mid_history: dict[str, deque[float]] = {}
        self._last_entry_signal_at: dict[str, float] = {}
        self._last_exit_signal_at: dict[str, float] = {}
        self._position_seen_at: dict[str, float] = {}
        self._blocked_until: dict[str, float] = {}
        self._imbalance_history: dict[str, deque[float]] = {}

        self.ticks_seen = 0
        self.orderbooks_seen = 0
        self.signals_generated = 0
        self.entries_generated = 0
        self.exits_generated = 0
        self.take_profit_exits_generated = 0
        self.stop_loss_exits_generated = 0
        self.time_exits_generated = 0
        self.skipped_for_cooldown = 0
        self.skipped_for_exit_cooldown = 0
        self.skipped_for_symbol_block = 0
        self.skipped_for_spread = 0
        self.skipped_for_bad_trend = 0
        self.skipped_for_insufficient_data = 0
        self.skipped_for_kill_switch = 0
        self.skipped_for_btc_filter = 0
        self.skipped_for_edge = 0
        self.skipped_for_imbalance_confirmation = 0

    def on_market_tick(
        self,
        tick: dict,
    ) -> None:
        self.ticks_seen += 1

        symbol = str(tick.get("symbol", "")).strip()

        if not symbol:
            return

        mid_price = self._extract_mid_price(
            tick
        )

        if mid_price <= 0:
            return

        self._append_mid(
            symbol,
            mid_price,
        )

    def on_orderbook(
        self,
        orderbook: dict,
    ) -> list[TradeSignal]:
        self.orderbooks_seen += 1

        if not self.kill_switch.is_active():
            self.skipped_for_kill_switch += 1
            return []

        symbol = str(orderbook.get("symbol", "")).strip()

        if not symbol:
            return []

        mid_price = self._extract_mid_price(
            orderbook
        )

        if mid_price <= 0:
            return []

        self._append_mid(
            symbol,
            mid_price,
        )

        history = self._mid_history.get(symbol)

        if history is None or len(history) < self.min_observations:
            self.skipped_for_insufficient_data += 1
            return []

        spread_bps = self._extract_spread_bps(
            orderbook,
            mid_price,
        )

        if spread_bps > self.max_spread_bps:
            self.skipped_for_spread += 1
            return []

        zscore = self._zscore(
            history,
            mid_price,
        )

        imbalance = float(
            orderbook.get("imbalance", 0.0)
        )

        if symbol == self.btc_symbol and not self.trade_btc_symbol:
            # Keep BTC as a market-regime monitor without trading it.
            return []

        position = self.ledger.get_position(
            symbol
        )

        signals: list[TradeSignal] = []

        if position is None or position.quantity == 0:
            self._position_seen_at.pop(symbol, None)

            if self._is_symbol_blocked(symbol):
                self.skipped_for_symbol_block += 1
                return []

            if self._recent_return_bps(history) <= -self.bad_symbol_drop_bps:
                self._block_symbol(
                    symbol,
                    self.loss_cooldown_seconds,
                    reason="bad recent trend",
                )
                self.skipped_for_bad_trend += 1
                return []

            if self._is_entry_on_cooldown(symbol):
                self.skipped_for_cooldown += 1
                return []

            if not self._btc_market_ok():
                self.skipped_for_btc_filter += 1
                return []

            expected_edge_bps = self._expected_edge_bps(
                history,
                mid_price,
            )

            entry_signal = self._build_entry_signal(
                symbol=symbol,
                mid_price=mid_price,
                best_bid=float(orderbook.get("best_bid", 0.0)),
                best_ask=float(orderbook.get("best_ask", 0.0)),
                zscore=zscore,
                imbalance=imbalance,
                expected_edge_bps=expected_edge_bps,
            )

            if entry_signal is not None:
                signals.append(entry_signal)
                self.entries_generated += 1
                self._last_entry_signal_at[symbol] = time.monotonic()

        else:
            if self._is_exit_on_cooldown(symbol):
                self.skipped_for_exit_cooldown += 1
                return []

            self._position_seen_at.setdefault(symbol, time.monotonic())

            exit_signal, exit_kind = self._build_exit_signal(
                symbol=symbol,
                position=position,
                best_bid=float(orderbook.get("best_bid", 0.0)),
                best_ask=float(orderbook.get("best_ask", 0.0)),
                mid_price=mid_price,
                zscore=zscore,
            )

            if exit_signal is not None:
                signals.append(exit_signal)
                self.exits_generated += 1
                self._last_exit_signal_at[symbol] = time.monotonic()

                if exit_kind == "take_profit":
                    self.take_profit_exits_generated += 1
                    self._block_symbol(
                        symbol,
                        self.cooldown_after_exit_seconds,
                        reason="profit captured",
                    )
                elif exit_kind == "stop_loss":
                    self.stop_loss_exits_generated += 1
                    self._block_symbol(
                        symbol,
                        self.loss_cooldown_seconds,
                        reason="loss stop",
                    )
                elif exit_kind == "time_stop":
                    self.time_exits_generated += 1
                    self._block_symbol(
                        symbol,
                        self.cooldown_after_exit_seconds,
                        reason="time stop",
                    )

        if signals:
            self.signals_generated += len(signals)

        return signals

    def _build_entry_signal(
        self,
        symbol: str,
        mid_price: float,
        best_bid: float,
        best_ask: float,
        zscore: float,
        imbalance: float,
        expected_edge_bps: float,
    ) -> TradeSignal | None:
        quantity = self._entry_quantity(
            mid_price
        )

        if quantity <= 0:
            return None

        if zscore <= -self.entry_zscore:
            if expected_edge_bps < self.required_expected_edge_bps:
                self.skipped_for_edge += 1
                return None

            if not self._imbalance_confirmed(
                symbol,
                imbalance,
                positive=True,
            ):
                self.skipped_for_imbalance_confirmation += 1
                return None

            if imbalance < self.imbalance_threshold:
                return None

            return TradeSignal(
                symbol=symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                order_type=self.order_type,
                price=self._entry_price(
                    side=OrderSide.BUY,
                    best_bid=best_bid,
                    best_ask=best_ask,
                ),
                strategy_id="mean_reversion_imbalance",
                reason=(
                    f"BUY entry: zscore={zscore:.4f}, "
                    f"imbalance={imbalance:.4f}"
                ),
                confidence=self._confidence(zscore),
            )

        allow_short_entries = os.getenv(
            "AEGIS_ALLOW_SHORT_ENTRIES",
            "false",
        ).strip().lower() in {"1", "true", "yes", "y", "on"}

        if (
            allow_short_entries
            and zscore >= self.entry_zscore
            and imbalance <= -self.imbalance_threshold
        ):
            return TradeSignal(
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=quantity,
                order_type=self.order_type,
                price=self._entry_price(
                    side=OrderSide.SELL,
                    best_bid=best_bid,
                    best_ask=best_ask,
                ),
                strategy_id="mean_reversion_imbalance",
                reason=(
                    f"SELL entry: zscore={zscore:.4f}, "
                    f"imbalance={imbalance:.4f}"
                ),
                confidence=self._confidence(zscore),
            )

        return None

    def _build_exit_signal(
        self,
        symbol: str,
        position,
        best_bid: float,
        best_ask: float,
        mid_price: float,
        zscore: float,
    ) -> tuple[TradeSignal | None, str | None]:
        entry_price = float(getattr(position, "average_entry", 0.0) or 0.0)

        if entry_price <= 0:
            return None, None

        age_seconds = time.monotonic() - self._position_seen_at.get(
            symbol,
            time.monotonic(),
        )

        if position.quantity > 0:
            exit_price = best_bid if best_bid > 0 else mid_price
            pnl_bps = ((exit_price - entry_price) / entry_price) * 10_000.0

            reason = None

            if pnl_bps >= self._fee_adjusted_take_profit_bps():
                reason = "take_profit"
            elif pnl_bps <= -self._dynamic_stop_loss_bps(history=self._mid_history.get(symbol)):
                reason = "stop_loss"
            elif (
                zscore >= -self.exit_zscore
                and pnl_bps >= self.required_min_profit_bps
            ):
                reason = "mean_reversion_profit"
            elif (
                self.max_hold_seconds > 0
                and age_seconds >= self.max_hold_seconds
                and pnl_bps >= 0
            ):
                reason = "time_stop"

            if reason is not None:
                return (
                    TradeSignal(
                        symbol=symbol,
                        side=OrderSide.SELL,
                        quantity=abs(position.quantity),
                        order_type=self.order_type,
                        price=self._entry_price(
                            side=OrderSide.SELL,
                            best_bid=best_bid,
                            best_ask=best_ask,
                        ),
                        strategy_id="mean_reversion_imbalance",
                        reason=(
                            f"SELL exit long ({reason}): "
                            f"pnl_bps={pnl_bps:.2f}, zscore={zscore:.4f}"
                        ),
                        confidence=1.0,
                    ),
                    reason,
                )

        if position.quantity < 0:
            exit_price = best_ask if best_ask > 0 else mid_price
            pnl_bps = ((entry_price - exit_price) / entry_price) * 10_000.0

            reason = None

            if pnl_bps >= self._fee_adjusted_take_profit_bps():
                reason = "take_profit"
            elif pnl_bps <= -self._dynamic_stop_loss_bps(history=self._mid_history.get(symbol)):
                reason = "stop_loss"
            elif (
                zscore <= self.exit_zscore
                and pnl_bps >= self.required_min_profit_bps
            ):
                reason = "mean_reversion_profit"
            elif (
                self.max_hold_seconds > 0
                and age_seconds >= self.max_hold_seconds
                and pnl_bps >= 0
            ):
                reason = "time_stop"

            if reason is not None:
                return (
                    TradeSignal(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=abs(position.quantity),
                        order_type=self.order_type,
                        price=self._entry_price(
                            side=OrderSide.BUY,
                            best_bid=best_bid,
                            best_ask=best_ask,
                        ),
                        strategy_id="mean_reversion_imbalance",
                        reason=(
                            f"BUY exit short ({reason}): "
                            f"pnl_bps={pnl_bps:.2f}, zscore={zscore:.4f}"
                        ),
                        confidence=1.0,
                    ),
                    reason,
                )

        return None, None

    def _entry_quantity(
        self,
        mid_price: float,
    ) -> float:
        if mid_price <= 0:
            return 0.0

        bounded_notional = min(
            max(self.target_notional, self.min_order_notional),
            self.max_position_notional,
        )

        if bounded_notional < self.min_order_notional:
            return 0.0

        return round(
            bounded_notional / mid_price,
            8,
        )

    def _entry_price(
        self,
        side: OrderSide,
        best_bid: float,
        best_ask: float,
    ) -> float | None:
        if self.order_type == OrderType.MARKET:
            return None

        if side == OrderSide.BUY:
            return best_bid if best_bid > 0 else None

        return best_ask if best_ask > 0 else None

    def _append_mid(
        self,
        symbol: str,
        mid_price: float,
    ) -> None:
        if symbol not in self._mid_history:
            self._mid_history[symbol] = deque(
                maxlen=self.rolling_window
            )

        self._mid_history[symbol].append(
            mid_price
        )

    def _zscore(
        self,
        history: deque[float],
        current_value: float,
    ) -> float:
        values = list(history)

        avg = mean(values)
        sigma = pstdev(values)

        if sigma <= 1e-12:
            return 0.0

        return (
            current_value - avg
        ) / sigma

    def _recent_return_bps(
        self,
        history: deque[float],
    ) -> float:
        values = list(history)

        if len(values) < 2 or values[0] <= 0:
            return 0.0

        return ((values[-1] - values[0]) / values[0]) * 10_000.0

    def _extract_mid_price(
        self,
        payload: dict,
    ) -> float:
        mid = payload.get("mid_price")

        if isinstance(mid, (int, float)) and mid > 0:
            return float(mid)

        bid = payload.get("bid") or payload.get("best_bid")
        ask = payload.get("ask") or payload.get("best_ask")

        try:
            bid_value = float(bid)
            ask_value = float(ask)

            if bid_value > 0 and ask_value > 0:
                return (
                    bid_value + ask_value
                ) / 2.0
        except (TypeError, ValueError):
            pass

        last = payload.get("last")

        try:
            last_value = float(last)

            if last_value > 0:
                return last_value
        except (TypeError, ValueError):
            pass

        return 0.0

    def _extract_spread_bps(
        self,
        orderbook: dict,
        mid_price: float,
    ) -> float:
        spread_bps = orderbook.get("spread_bps")

        if isinstance(spread_bps, (int, float)):
            return float(spread_bps)

        spread = orderbook.get("spread")

        try:
            spread_value = float(spread)

            if spread_value >= 0 and mid_price > 0:
                return (
                    spread_value / mid_price
                ) * 10000.0
        except (TypeError, ValueError):
            pass

        return 0.0

    def _is_entry_on_cooldown(
        self,
        symbol: str,
    ) -> bool:
        return self._is_on_cooldown(
            symbol,
            self._last_entry_signal_at,
            self.cooldown_seconds,
        )

    def _is_exit_on_cooldown(
        self,
        symbol: str,
    ) -> bool:
        return self._is_on_cooldown(
            symbol,
            self._last_exit_signal_at,
            max(5.0, min(self.cooldown_seconds, 30.0)),
        )

    def _is_on_cooldown(
        self,
        symbol: str,
        store: dict[str, float],
        seconds: float,
    ) -> bool:
        if seconds <= 0:
            return False

        last_signal_at = store.get(
            symbol
        )

        if last_signal_at is None:
            return False

        return (
            time.monotonic() - last_signal_at
        ) < seconds

    def _block_symbol(
        self,
        symbol: str,
        seconds: float,
        reason: str,
    ) -> None:
        if seconds <= 0:
            return

        self._blocked_until[symbol] = max(
            self._blocked_until.get(symbol, 0.0),
            time.monotonic() + seconds,
        )

        log.info(
            "Symbol %s blocked for %.1fs after %s",
            symbol,
            seconds,
            reason,
        )

    def _is_symbol_blocked(
        self,
        symbol: str,
    ) -> bool:
        blocked_until = self._blocked_until.get(symbol)

        if blocked_until is None:
            return False

        if time.monotonic() >= blocked_until:
            self._blocked_until.pop(symbol, None)
            return False

        return True

    def _confidence(
        self,
        zscore: float,
    ) -> float:
        raw = abs(zscore) / max(self.entry_zscore, 1e-12)
        return min(1.0, raw)

    def _fee_adjusted_take_profit_bps(self) -> float:
        return max(
            self.take_profit_bps,
            self.round_trip_cost_bps + self.required_min_profit_bps,
        )

    def _dynamic_stop_loss_bps(self, history: deque[float] | None) -> float:
        if not self.dynamic_stop_enabled:
            return self.stop_loss_bps

        volatility_bps = self._volatility_bps(
            history,
            lookback=self.dynamic_stop_lookback,
        )
        raw = volatility_bps * self.dynamic_stop_multiplier
        return max(
            self.dynamic_stop_min_bps,
            min(self.dynamic_stop_max_bps, raw),
        )

    def _expected_edge_bps(self, history: deque[float], mid_price: float) -> float:
        values = list(history)
        if not values or mid_price <= 0:
            return 0.0

        avg = mean(values)
        if avg <= mid_price:
            return 0.0

        return ((avg - mid_price) / mid_price) * 10_000.0

    def _volatility_bps(self, history: deque[float] | None, lookback: int) -> float:
        if history is None:
            return 0.0

        values = list(history)[-max(2, lookback):]
        if len(values) < 2:
            return 0.0

        avg = mean(values)
        if avg <= 0:
            return 0.0

        return (pstdev(values) / avg) * 10_000.0

    def _imbalance_confirmed(
        self,
        symbol: str,
        imbalance: float,
        *,
        positive: bool,
    ) -> bool:
        history = self._imbalance_history.setdefault(
            symbol,
            deque(maxlen=self.imbalance_confirm_snapshots),
        )
        history.append(imbalance)

        if len(history) < self.imbalance_confirm_snapshots:
            return False

        if positive:
            return all(value >= self.imbalance_threshold for value in history)

        return all(value <= -self.imbalance_threshold for value in history)

    def _btc_market_ok(self) -> bool:
        if not self.btc_filter_enabled:
            return True

        history = self._mid_history.get(self.btc_symbol)
        if history is None or len(history) < self.btc_min_observations:
            return not self.btc_filter_require_data

        recent_return = self._recent_return_bps(history)
        if recent_return <= -abs(self.btc_danger_drop_bps):
            return False

        volatility = self._volatility_bps(
            history,
            lookback=self.btc_min_observations,
        )
        if volatility >= self.btc_volatility_max_bps:
            return False

        return True

    def _bool_env(self, name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    def _float_env(self, name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _int_env(self, name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            return int(float(raw))
        except ValueError:
            return default

    def metrics(self) -> dict:
        return {
            "ticks_seen": self.ticks_seen,
            "orderbooks_seen": self.orderbooks_seen,
            "signals_generated": self.signals_generated,
            "entries_generated": self.entries_generated,
            "exits_generated": self.exits_generated,
            "take_profit_exits_generated": self.take_profit_exits_generated,
            "stop_loss_exits_generated": self.stop_loss_exits_generated,
            "time_exits_generated": self.time_exits_generated,
            "skipped_for_cooldown": self.skipped_for_cooldown,
            "skipped_for_exit_cooldown": self.skipped_for_exit_cooldown,
            "skipped_for_symbol_block": self.skipped_for_symbol_block,
            "skipped_for_spread": self.skipped_for_spread,
            "skipped_for_bad_trend": self.skipped_for_bad_trend,
            "skipped_for_insufficient_data": self.skipped_for_insufficient_data,
            "skipped_for_kill_switch": self.skipped_for_kill_switch,
            "skipped_for_btc_filter": self.skipped_for_btc_filter,
            "skipped_for_edge": self.skipped_for_edge,
            "skipped_for_imbalance_confirmation": self.skipped_for_imbalance_confirmation,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "required_min_profit_bps": self.required_min_profit_bps,
            "required_expected_edge_bps": self.required_expected_edge_bps,
            "fee_adjusted_take_profit_bps": self._fee_adjusted_take_profit_bps(),
            "blocked_symbols": len(self._blocked_until),
        }
