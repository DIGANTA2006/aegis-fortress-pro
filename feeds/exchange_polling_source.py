import asyncio
import inspect
import logging
import os
import time

from feeds.market_data_packet import MarketDataPacket


log = logging.getLogger(__name__)


class ExchangePollingSource:
    def __init__(
        self,
        exchange_registry,
        symbols: tuple[str, ...],
        poll_interval_seconds: float,
        orderbook_depth: int,
        symbols_provider=None,
        symbol_refresh_interval_seconds: float = 0.0,
        max_concurrent_fetches: int | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")

        if orderbook_depth <= 0:
            raise ValueError("orderbook_depth must be positive")

        self.exchange_registry = exchange_registry
        self.symbols = tuple(symbols)
        self.poll_interval_seconds = poll_interval_seconds
        self.orderbook_depth = orderbook_depth
        self.symbols_provider = symbols_provider
        self.symbol_refresh_interval_seconds = symbol_refresh_interval_seconds
        self.max_concurrent_fetches = max(
            1,
            int(
                max_concurrent_fetches
                if max_concurrent_fetches is not None
                else os.getenv("AEGIS_MARKET_FETCH_CONCURRENCY", "8")
            ),
        )
        self._last_symbol_refresh_at = 0.0
        self.running = False

    async def stream(self):
        self.running = True

        while self.running:
            self._refresh_symbols_if_needed()

            jobs = []
            semaphore = asyncio.Semaphore(self.max_concurrent_fetches)

            for exchange_name, exchange in self.exchange_registry.all().items():
                for symbol in self.symbols:
                    jobs.append(
                        asyncio.create_task(
                            self._poll_exchange_symbol(
                                semaphore=semaphore,
                                exchange=exchange,
                                symbol=symbol,
                                exchange_name=exchange_name,
                            )
                        )
                    )

            for task in asyncio.as_completed(jobs):
                if not self.running:
                    break

                try:
                    packets = await task
                except Exception as exc:
                    log.warning("Market polling task failed: %s", exc)
                    continue

                for packet in packets:
                    yield packet

            await asyncio.sleep(self.poll_interval_seconds)

    async def _poll_exchange_symbol(
        self,
        semaphore: asyncio.Semaphore,
        exchange,
        symbol: str,
        exchange_name: str,
    ) -> list[MarketDataPacket]:
        async with semaphore:
            ticker_task = asyncio.create_task(
                self._safe_fetch_ticker(
                    exchange=exchange,
                    symbol=symbol,
                    exchange_name=exchange_name,
                )
            )
            orderbook_task = asyncio.create_task(
                self._safe_fetch_orderbook(
                    exchange=exchange,
                    symbol=symbol,
                    exchange_name=exchange_name,
                )
            )

            ticker_payload, orderbook_payload = await asyncio.gather(
                ticker_task,
                orderbook_task,
            )

        packets: list[MarketDataPacket] = []

        if ticker_payload is not None:
            packets.append(
                MarketDataPacket(
                    kind="ticker",
                    exchange=exchange_name,
                    symbol=symbol,
                    payload=ticker_payload,
                )
            )

        if orderbook_payload is not None:
            packets.append(
                MarketDataPacket(
                    kind="orderbook",
                    exchange=exchange_name,
                    symbol=symbol,
                    payload=orderbook_payload,
                )
            )

        return packets

    def _refresh_symbols_if_needed(self) -> None:
        if self.symbols_provider is None:
            return

        if self.symbol_refresh_interval_seconds <= 0:
            return

        now = time.monotonic()

        if (
            self._last_symbol_refresh_at > 0
            and now - self._last_symbol_refresh_at < self.symbol_refresh_interval_seconds
        ):
            return

        self._last_symbol_refresh_at = now

        try:
            next_symbols = tuple(
                symbol
                for symbol in self.symbols_provider()
                if str(symbol).strip()
            )
        except Exception as exc:
            log.warning("Symbol refresh failed: %s", exc)
            return

        if not next_symbols:
            log.warning("Symbol refresh returned no symbols; keeping current list")
            return

        if next_symbols != self.symbols:
            log.info(
                "Market symbol universe refreshed: %s",
                ", ".join(next_symbols),
            )
            self.symbols = next_symbols

    def stop(self) -> None:
        self.running = False

    async def _safe_fetch_ticker(
        self,
        exchange,
        symbol: str,
        exchange_name: str,
    ):
        try:
            method = getattr(exchange, "fetch_ticker", None)

            if method is None:
                return None

            return await self._call_maybe_async(method, symbol)

        except Exception as exc:
            log.warning(
                "Ticker fetch failed for %s:%s: %s",
                exchange_name,
                symbol,
                exc,
            )
            return None

    async def _safe_fetch_orderbook(
        self,
        exchange,
        symbol: str,
        exchange_name: str,
    ):
        candidates = (
            "fetch_order_book",
            "fetch_orderbook",
            "get_order_book",
            "get_orderbook",
        )

        for method_name in candidates:
            method = getattr(exchange, method_name, None)

            if method is None:
                continue

            try:
                return await self._call_orderbook_method(method, symbol)

            except Exception as exc:
                log.warning(
                    "Order book fetch failed for %s:%s via %s: %s",
                    exchange_name,
                    symbol,
                    method_name,
                    exc,
                )
                return None

        return None

    async def _call_orderbook_method(self, method, symbol: str):
        def call_sync():
            try:
                return method(symbol, self.orderbook_depth)
            except TypeError:
                return method(symbol)

        if inspect.iscoroutinefunction(method):
            try:
                return await method(symbol, self.orderbook_depth)
            except TypeError:
                return await method(symbol)

        return await asyncio.to_thread(call_sync)

    async def _call_maybe_async(self, method, *args, **kwargs):
        if inspect.iscoroutinefunction(method):
            return await method(*args, **kwargs)

        return await asyncio.to_thread(method, *args, **kwargs)

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value

        return value
