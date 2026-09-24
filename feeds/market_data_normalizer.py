from datetime import datetime, timezone
from typing import Any

from models.market_tick import MarketTick
from models.orderbook import OrderBookLevel, OrderBookSnapshot


class MarketDataNormalizer:
    def normalize_ticker(
        self,
        exchange: str,
        symbol: str,
        payload: Any,
    ) -> MarketTick:
        if not isinstance(payload, dict):
            raise TypeError("Ticker payload must be a dictionary")

        bid = self._extract_float(
            payload,
            "bid",
            "bestBid",
            "best_bid",
            default=0.0,
        )

        ask = self._extract_float(
            payload,
            "ask",
            "bestAsk",
            "best_ask",
            default=0.0,
        )

        last = self._extract_float(
            payload,
            "last",
            "close",
            "mark",
            "price",
            default=0.0,
        )

        if last <= 0 and bid > 0 and ask > 0:
            last = (bid + ask) / 2.0

        volume = self._extract_float(
            payload,
            "baseVolume",
            "volume",
            "quoteVolume",
            default=0.0,
        )

        timestamp = self._extract_timestamp(
            payload.get("timestamp")
            or payload.get("datetime")
        )

        tick = MarketTick(
            symbol=symbol,
            exchange=exchange,
            bid=bid,
            ask=ask,
            last=last,
            volume=volume,
            timestamp=timestamp,
            raw=payload,
        )

        if not tick.is_valid():
            raise ValueError(
                f"Invalid normalized ticker for {exchange}:{symbol}"
            )

        return tick

    def normalize_orderbook(
        self,
        exchange: str,
        symbol: str,
        payload: Any,
        depth: int,
    ) -> OrderBookSnapshot:
        if not isinstance(payload, dict):
            raise TypeError("Order book payload must be a dictionary")

        raw_bids = payload.get("bids", [])
        raw_asks = payload.get("asks", [])

        bids = self._normalize_levels(
            raw_bids,
            reverse=True,
            depth=depth,
        )

        asks = self._normalize_levels(
            raw_asks,
            reverse=False,
            depth=depth,
        )

        sequence = self._extract_int(
            payload,
            "nonce",
            "sequence",
            "lastUpdateId",
        )

        timestamp = self._extract_timestamp(
            payload.get("timestamp")
            or payload.get("datetime")
        )

        orderbook = OrderBookSnapshot(
            symbol=symbol,
            exchange=exchange,
            bids=bids,
            asks=asks,
            sequence=sequence,
            timestamp=timestamp,
            raw=payload,
        )

        if not orderbook.is_valid():
            raise ValueError(
                f"Invalid normalized order book for {exchange}:{symbol}"
            )

        return orderbook

    def _normalize_levels(
        self,
        levels: Any,
        reverse: bool,
        depth: int,
    ) -> list[OrderBookLevel]:
        normalized: list[OrderBookLevel] = []

        if not isinstance(levels, list):
            return normalized

        for item in levels:
            price = None
            quantity = None

            if isinstance(item, (list, tuple)) and len(item) >= 2:
                price = item[0]
                quantity = item[1]

            elif isinstance(item, dict):
                price = (
                    item.get("price")
                    or item.get("p")
                )
                quantity = (
                    item.get("quantity")
                    or item.get("amount")
                    or item.get("q")
                )

            parsed_price = self._safe_float(price)
            parsed_quantity = self._safe_float(quantity)

            if (
                parsed_price is None
                or parsed_quantity is None
                or parsed_price <= 0
                or parsed_quantity <= 0
            ):
                continue

            normalized.append(
                OrderBookLevel(
                    price=parsed_price,
                    quantity=parsed_quantity,
                )
            )

        normalized.sort(
            key=lambda level: level.price,
            reverse=reverse,
        )

        return normalized[:depth]

    def _extract_float(
        self,
        payload: dict,
        *keys: str,
        default: float,
    ) -> float:
        for key in keys:
            value = payload.get(key)
            parsed = self._safe_float(value)

            if parsed is not None:
                return parsed

        return default

    def _extract_int(
        self,
        payload: dict,
        *keys: str,
    ) -> int | None:
        for key in keys:
            value = payload.get(key)

            if isinstance(value, int):
                return value

            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue

        return None

    def _safe_float(self, value) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None

        return None

    def _extract_timestamp(self, value) -> datetime:
        if isinstance(value, (int, float)):
            seconds = float(value)

            if seconds > 1_000_000_000_000:
                seconds /= 1000.0

            return datetime.fromtimestamp(
                seconds,
                tz=timezone.utc,
            ).replace(tzinfo=None)

        if isinstance(value, str):
            try:
                normalized = value.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)

                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

                return parsed
            except ValueError:
                pass

        return datetime.utcnow()
