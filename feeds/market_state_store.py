import threading
import time

from models.market_tick import MarketTick
from models.orderbook import OrderBookSnapshot


class MarketStateStore:
    def __init__(
        self,
        stale_after_seconds: float = 30.0,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")

        self.stale_after_seconds = stale_after_seconds

        self._lock = threading.RLock()
        self._ticks: dict[str, MarketTick] = {}
        self._orderbooks: dict[str, OrderBookSnapshot] = {}
        self._updated_at: dict[str, float] = {}

    def _key(
        self,
        exchange: str,
        symbol: str,
    ) -> str:
        return f"{exchange}:{symbol}"

    def update_tick(
        self,
        tick: MarketTick,
    ) -> None:
        key = self._key(
            tick.exchange,
            tick.symbol,
        )

        with self._lock:
            self._ticks[key] = tick
            self._updated_at[key] = time.time()

    def update_orderbook(
        self,
        orderbook: OrderBookSnapshot,
    ) -> None:
        key = self._key(
            orderbook.exchange,
            orderbook.symbol,
        )

        with self._lock:
            self._orderbooks[key] = orderbook
            self._updated_at[key] = time.time()

    def latest_tick(
        self,
        exchange: str,
        symbol: str,
    ) -> MarketTick | None:
        key = self._key(exchange, symbol)

        with self._lock:
            return self._ticks.get(key)

    def latest_orderbook(
        self,
        exchange: str,
        symbol: str,
    ) -> OrderBookSnapshot | None:
        key = self._key(exchange, symbol)

        with self._lock:
            return self._orderbooks.get(key)

    def mark_prices(self) -> dict[str, float]:
        prices: dict[str, float] = {}

        with self._lock:
            for tick in self._ticks.values():
                prices[tick.symbol] = tick.mid_price or tick.last

        return prices

    def stale_keys(self) -> list[str]:
        now = time.time()

        with self._lock:
            return [
                key
                for key, updated_at in self._updated_at.items()
                if now - updated_at > self.stale_after_seconds
            ]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "ticks": {
                    key: tick.to_dict()
                    for key, tick in self._ticks.items()
                },
                "orderbooks": {
                    key: orderbook.to_dict()
                    for key, orderbook in self._orderbooks.items()
                },
                "stale_keys": self.stale_keys(),
            }
