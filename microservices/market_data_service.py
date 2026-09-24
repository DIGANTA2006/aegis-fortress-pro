import asyncio
import logging

from core.events.market_tick_event import MarketTickEvent
from core.events.orderbook_event import OrderBookEvent
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class MarketDataService(BaseService):
    def __init__(
        self,
        event_bus,
        market_source,
        normalizer,
        market_state_store,
    ) -> None:
        super().__init__("market-data-service")

        self.event_bus = event_bus
        self.market_source = market_source
        self.normalizer = normalizer
        self.market_state_store = market_state_store

        self.ticks_published = 0
        self.orderbooks_published = 0
        self.normalization_failures = 0

    async def on_stop(self) -> None:
        self.market_source.stop()

    async def run(self) -> None:
        async for packet in self.market_source.stream():
            if not self.running:
                break

            self.heartbeat()

            try:
                if packet.kind == "ticker":
                    await self._handle_ticker(packet)

                elif packet.kind == "orderbook":
                    await self._handle_orderbook(packet)

            except Exception as exc:
                self.normalization_failures += 1

                log.warning(
                    "MarketDataService normalization failed for %s:%s kind=%s: %s",
                    packet.exchange,
                    packet.symbol,
                    packet.kind,
                    exc,
                )

            await asyncio.sleep(0)

    async def _handle_ticker(self, packet) -> None:
        tick = self.normalizer.normalize_ticker(
            exchange=packet.exchange,
            symbol=packet.symbol,
            payload=packet.payload,
        )

        self.market_state_store.update_tick(
            tick
        )

        await self.event_bus.publish(
            MarketTickEvent(
                event_type="MARKET_TICK",
                tick=tick.to_dict(),
            )
        )

        self.ticks_published += 1

    async def _handle_orderbook(self, packet) -> None:
        orderbook = self.normalizer.normalize_orderbook(
            exchange=packet.exchange,
            symbol=packet.symbol,
            payload=packet.payload,
            depth=self.market_source.orderbook_depth,
        )

        self.market_state_store.update_orderbook(
            orderbook
        )

        await self.event_bus.publish(
            OrderBookEvent(
                event_type="ORDERBOOK_SNAPSHOT",
                orderbook=orderbook.to_dict(),
            )
        )

        self.orderbooks_published += 1

    def metrics(self) -> dict:
        return {
            "ticks_published": self.ticks_published,
            "orderbooks_published": self.orderbooks_published,
            "normalization_failures": self.normalization_failures,
            "stale_market_keys": self.market_state_store.stale_keys(),
        }

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = self.metrics()
        return payload
