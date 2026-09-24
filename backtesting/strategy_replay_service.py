import asyncio
import logging
from collections.abc import Iterable

from core.events.market_tick_event import MarketTickEvent
from core.events.order_request_event import OrderRequestEvent
from execution.order_event_codec import OrderEventCodec
from microservices.base_service import BaseService
from models.signal import TradeSignal


log = logging.getLogger(__name__)


class StrategyReplayService(BaseService):
    def __init__(
        self,
        event_bus,
        strategy,
        market_state_store,
    ) -> None:
        super().__init__("strategy-replay-service")

        self.event_bus = event_bus
        self.strategy = strategy
        self.market_state_store = market_state_store
        self.codec = OrderEventCodec()

        self.market_ticks_seen = 0
        self.signals_emitted = 0
        self.orders_requested = 0
        self.signal_failures = 0

    async def on_start(self) -> None:
        self.event_bus.subscribe(
            "MARKET_TICK",
            self._on_market_tick,
        )

    async def run(self) -> None:
        while self.running:
            self.heartbeat()
            await asyncio.sleep(1)

    async def _on_market_tick(
        self,
        event: MarketTickEvent,
    ) -> None:
        self.market_ticks_seen += 1

        try:
            result = self._invoke_strategy(
                event.tick
            )

            signals = self._normalize_signals(result)

            for signal in signals:
                signal.validate()

                order = signal.to_order()

                order_payload = self.codec.encode(
                    order
                )

                await self.event_bus.publish(
                    OrderRequestEvent(
                        event_type="ORDER_REQUEST",
                        correlation_id=order.correlation_id,
                        order_payload=order_payload,
                        mark_prices=self.market_state_store.mark_prices(),
                    )
                )

                self.signals_emitted += 1
                self.orders_requested += 1

        except Exception as exc:
            self.signal_failures += 1

            log.exception(
                "Strategy replay processing failed: %s",
                exc,
            )

    def _invoke_strategy(
        self,
        tick_payload: dict,
    ):
        if hasattr(self.strategy, "on_market_tick"):
            return self.strategy.on_market_tick(
                tick_payload
            )

        if hasattr(self.strategy, "generate_signal"):
            return self.strategy.generate_signal(
                tick_payload
            )

        raise AttributeError(
            "Strategy must expose on_market_tick() or generate_signal()"
        )

    def _normalize_signals(
        self,
        value,
    ) -> list[TradeSignal]:
        if value is None:
            return []

        if isinstance(value, TradeSignal):
            return [value]

        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
            items = list(value)

            for item in items:
                if not isinstance(item, TradeSignal):
                    raise TypeError(
                        "Strategy iterable must contain TradeSignal objects"
                    )

            return items

        raise TypeError(
            "Strategy output must be TradeSignal, iterable[TradeSignal], or None"
        )

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = {
            "market_ticks_seen": self.market_ticks_seen,
            "signals_emitted": self.signals_emitted,
            "orders_requested": self.orders_requested,
            "signal_failures": self.signal_failures,
        }
        return payload
