import asyncio
import logging

from core.events.market_tick_event import MarketTickEvent
from core.events.orderbook_event import OrderBookEvent
from microservices.base_service import BaseService


log = logging.getLogger(__name__)


class ReplayMarketDataService(BaseService):
    def __init__(
        self,
        event_bus,
        replay_source,
        replay_clock,
        normalizer,
        market_state_store,
        simulated_exchange,
    ) -> None:
        super().__init__("replay-market-data-service")

        self.event_bus = event_bus
        self.replay_source = replay_source
        self.replay_clock = replay_clock
        self.normalizer = normalizer
        self.market_state_store = market_state_store
        self.simulated_exchange = simulated_exchange

        self.records_processed = 0
        self.ticks_published = 0
        self.orderbooks_published = 0
        self.failed_records = 0

    async def run(self) -> None:
        for record in self.replay_source.records():
            if not self.running:
                break

            try:
                await self.replay_clock.advance_to(
                    record.timestamp
                )

                if record.event_type == "MARKET_TICK":
                    await self._handle_tick(record)

                elif record.event_type == "ORDERBOOK_SNAPSHOT":
                    await self._handle_orderbook(record)

                self.records_processed += 1
                self.heartbeat()

            except Exception as exc:
                self.failed_records += 1

                log.exception(
                    "Replay record processing failed: %s",
                    exc,
                )

            await asyncio.sleep(0)

        self.running = False

        log.info(
            "ReplayMarketDataService completed records=%s failed=%s",
            self.records_processed,
            self.failed_records,
        )

    async def _handle_tick(self, record) -> None:
        payload = record.payload

        exchange = str(payload.get("exchange", "SIMULATED"))
        symbol = str(payload["symbol"])

        tick = self.normalizer.normalize_ticker(
            exchange=exchange,
            symbol=symbol,
            payload=payload,
        )

        tick.timestamp = record.timestamp

        self.market_state_store.update_tick(
            tick
        )

        self.simulated_exchange.update_tick(
            tick
        )

        await self.event_bus.publish(
            MarketTickEvent(
                event_type="MARKET_TICK",
                tick=tick.to_dict(),
            )
        )

        self.ticks_published += 1

    async def _handle_orderbook(self, record) -> None:
        payload = record.payload

        exchange = str(payload.get("exchange", "SIMULATED"))
        symbol = str(payload["symbol"])

        orderbook = self.normalizer.normalize_orderbook(
            exchange=exchange,
            symbol=symbol,
            payload=payload,
            depth=int(payload.get("depth", 20)),
        )

        orderbook.timestamp = record.timestamp

        self.market_state_store.update_orderbook(
            orderbook
        )

        self.simulated_exchange.update_orderbook(
            orderbook
        )

        await self.event_bus.publish(
            OrderBookEvent(
                event_type="ORDERBOOK_SNAPSHOT",
                orderbook=orderbook.to_dict(),
            )
        )

        self.orderbooks_published += 1

    def health(self) -> dict:
        payload = super().health()
        payload["metrics"] = {
            "records_processed": self.records_processed,
            "ticks_published": self.ticks_published,
            "orderbooks_published": self.orderbooks_published,
            "failed_records": self.failed_records,
        }
        return payload
