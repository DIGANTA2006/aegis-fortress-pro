import asyncio
import logging

from core.events.market_tick_event import MarketTickEvent
from core.events.order_request_event import OrderRequestEvent
from core.events.orderbook_event import OrderBookEvent
from execution.order_event_codec import OrderEventCodec
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class LiveStrategyService(BaseService):
    def __init__(
        self,
        event_bus,
        strategy,
        market_state_store,
    ) -> None:
        super().__init__("live-strategy-service")

        self.event_bus = event_bus
        self.strategy = strategy
        self.market_state_store = market_state_store
        self.codec = OrderEventCodec()

        self.market_ticks_seen = 0
        self.orderbooks_seen = 0
        self.order_requests_published = 0
        self.strategy_errors = 0

    async def on_start(self) -> None:
        self.event_bus.subscribe(
            "MARKET_TICK",
            self._on_market_tick,
        )

        self.event_bus.subscribe(
            "ORDERBOOK_SNAPSHOT",
            self._on_orderbook_snapshot,
        )

        log.info(
            "LiveStrategyService subscribed to market events"
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
            self.strategy.on_market_tick(
                event.tick
            )

        except Exception as exc:
            self.strategy_errors += 1

            log.exception(
                "Live strategy tick processing failed: %s",
                exc,
            )

    async def _on_orderbook_snapshot(
        self,
        event: OrderBookEvent,
    ) -> None:
        self.orderbooks_seen += 1

        try:
            signals = self.strategy.on_orderbook(
                event.orderbook
            )

            for signal in signals:
                order = signal.to_order()

                await self.event_bus.publish(
                    OrderRequestEvent(
                        event_type="ORDER_REQUEST",
                        correlation_id=order.correlation_id,
                        order_payload=self.codec.encode(order),
                        mark_prices=self.market_state_store.mark_prices(),
                    )
                )

                self.order_requests_published += 1

                log.info(
                    "Live strategy published order request symbol=%s side=%s quantity=%s",
                    order.symbol,
                    order.side.value,
                    order.quantity,
                )

        except Exception as exc:
            self.strategy_errors += 1

            log.exception(
                "Live strategy orderbook processing failed: %s",
                exc,
            )

    def metrics(self) -> dict:
        payload = {
            "market_ticks_seen": self.market_ticks_seen,
            "orderbooks_seen": self.orderbooks_seen,
            "order_requests_published": self.order_requests_published,
            "strategy_errors": self.strategy_errors,
        }

        strategy_metrics = getattr(
            self.strategy,
            "metrics",
            None,
        )

        if callable(strategy_metrics):
            payload["strategy"] = strategy_metrics()

        return payload

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = self.metrics()
        return payload