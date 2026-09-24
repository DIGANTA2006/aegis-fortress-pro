import os
import logging


log = logging.getLogger(__name__)


class SmartOrderRouter:
    def __init__(self, registry) -> None:
        self.registry = registry

    def find_best_exchange(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ):
        normalized_side = str(side).upper()

        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        best_exchange = None
        best_price = None

        allowed_raw = os.getenv("AEGIS_EXECUTION_EXCHANGES", "").strip()

        allowed_exchanges = {
            item.strip().lower()
            for item in allowed_raw.split(",")
            if item.strip()
        }

        for name, exchange in self.registry.all().items():
            if (
                allowed_exchanges
                and name.lower() not in allowed_exchanges
                and name.upper() != "SIMULATED"
            ):
                log.info(
                    "Router skipped exchange %s for %s: not in AEGIS_EXECUTION_EXCHANGES",
                    name,
                    symbol,
                )
                continue

            if getattr(exchange, "execution_enabled", True) is False:
                log.info(
                    "Router skipped exchange %s for %s: execution disabled",
                    name,
                    symbol,
                )
                continue

            try:
                price = self._extract_execution_price(
                    exchange=exchange,
                    symbol=symbol,
                    side=normalized_side,
                )

                if price is None or price <= 0:
                    continue

                if best_price is None:
                    best_price = price
                    best_exchange = exchange
                    continue

                if normalized_side == "BUY" and price < best_price:
                    best_price = price
                    best_exchange = exchange

                elif normalized_side == "SELL" and price > best_price:
                    best_price = price
                    best_exchange = exchange

            except Exception as exc:
                log.warning(
                    "Router skipped exchange %s for %s: %s",
                    name,
                    symbol,
                    exc,
                )

        if best_exchange is None or best_price is None:
            raise RuntimeError(
                f"No routable exchange price found for {symbol} {normalized_side}"
            )

        return best_exchange, best_price

    def _extract_execution_price(
        self,
        exchange,
        symbol: str,
        side: str,
    ) -> float | None:
        if side == "BUY" and hasattr(exchange, "get_best_ask"):
            price = exchange.get_best_ask(symbol)
            if price:
                return float(price)

        if side == "SELL" and hasattr(exchange, "get_best_bid"):
            price = exchange.get_best_bid(symbol)
            if price:
                return float(price)

        ticker = exchange.fetch_ticker(symbol)

        if not isinstance(ticker, dict):
            return None

        field = "ask" if side == "BUY" else "bid"
        value = ticker.get(field)

        if value in (None, ""):
            return None

        return float(value)
