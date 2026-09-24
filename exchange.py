"""
exchange.py  -  AEGIS PRO v2
Multi-exchange connection manager: Binance, Bybit, OKX.
Handles:
  - Initialisation and credential injection
  - Token-bucket rate limiting per exchange
  - Best-price routing (buy on cheapest ask, sell on highest bid)
  - Automatic reconnect after network errors
  - On-startup open-order reconciliation
"""

import logging
import os
import threading
from typing import Dict, List, Optional

from config import AegisConfig
from utils import TokenBucket, retry

log = logging.getLogger("aegis.exchange")


# ---------------------------------------------------------------------------
# Optional CCXT import
# ---------------------------------------------------------------------------

try:
    import ccxt

    _HAS_CCXT = True
except ImportError:
    ccxt = None
    _HAS_CCXT = False
    log.critical("ccxt not installed. Run: pip install ccxt")


# ---------------------------------------------------------------------------
# Per-exchange rate limits (conservative - well below actual limits)
# ---------------------------------------------------------------------------

_RATE_LIMITS: Dict[str, dict] = {
    "binance": {"rate": 8.0, "capacity": 20},  # ~1200 req/min allowance ÃƒÂ¢Ã¢â‚¬Â ' 8/s burst 20
    "bybit": {"rate": 5.0, "capacity": 10},
    "okx": {"rate": 5.0, "capacity": 10},
}


class ExchangeWrapper:
    """
    Wraps a single ccxt exchange with a token bucket and retry logic.
    """

    def __init__(self, exchange_id: str, exchange_obj, cfg: AegisConfig):
        self.id = exchange_id
        self._ex = exchange_obj
        self.cfg = cfg
        rl = _RATE_LIMITS.get(exchange_id, {"rate": 3.0, "capacity": 6})
        self._bucket = TokenBucket(rate=rl["rate"], capacity=rl["capacity"])
        self._lock = threading.Lock()
        self.execution_enabled = True

    def _call(self, method: str, *args, **kwargs):
        self._bucket.consume()
        with self._lock:
            return getattr(self._ex, method)(*args, **kwargs)

    # Public convenience wrappers ----------------------------------------

    @retry(max_attempts=4, base_delay=1.5)
    def fetch_ticker(self, symbol: str) -> dict:
        return self._call("fetch_ticker", symbol)

    @retry(max_attempts=4, base_delay=1.5)
    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self._call("fetch_order_book", symbol, limit)

    @retry(max_attempts=4, base_delay=1.5)
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 400) -> list:
        return self._call("fetch_ohlcv", symbol, timeframe, limit=limit)

    @retry(max_attempts=4, base_delay=1.5)
    def fetch_balance(self) -> dict:
        return self._call("fetch_balance")

    @retry(max_attempts=3, base_delay=1.0)
    def create_market_buy_order(self, symbol: str, amount: float, params: dict = None):
        return self._call("create_market_buy_order", symbol, amount, params or {})

    @retry(max_attempts=3, base_delay=1.0)
    def create_market_sell_order(self, symbol: str, amount: float, params: dict = None):
        return self._call("create_market_sell_order", symbol, amount, params or {})

    @retry(max_attempts=3, base_delay=1.0)
    def create_limit_buy_order(self, symbol: str, amount: float, price: float, params: dict = None):
        return self._call("create_limit_buy_order", symbol, amount, price, params or {})

    @retry(max_attempts=3, base_delay=1.0)
    def create_limit_sell_order(
        self, symbol: str, amount: float, price: float, params: dict = None
    ):
        return self._call("create_limit_sell_order", symbol, amount, price, params or {})

    @retry(max_attempts=3, base_delay=1.0)
    def cancel_order(self, order_id: str, symbol: str):
        return self._call("cancel_order", order_id, symbol)

    @retry(max_attempts=3, base_delay=1.0)
    def fetch_order(self, order_id: str, symbol: str) -> dict:
        return self._call("fetch_order", order_id, symbol)

    @retry(max_attempts=3, base_delay=1.0)
    def fetch_open_orders(self, symbol: str) -> list:
        return self._call("fetch_open_orders", symbol)

    def get_best_ask(self, symbol: str) -> Optional[float]:
        """Best ask price (lowest price to buy at)."""
        try:
            ob = self.fetch_order_book(symbol, limit=1)
            if ob.get("asks"):
                return float(ob["asks"][0][0])
        except Exception:
            pass
        return None

    def get_best_bid(self, symbol: str) -> Optional[float]:
        """Best bid price (highest price to sell at)."""
        try:
            ob = self.fetch_order_book(symbol, limit=1)
            if ob.get("bids"):
                return float(ob["bids"][0][0])
        except Exception:
            pass
        return None

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        try:
            return float(self._ex.amount_to_precision(symbol, amount))
        except Exception:
            return float(amount)

    def price_to_precision(self, symbol: str, price: float) -> float:
        try:
            return float(self._ex.price_to_precision(symbol, price))
        except Exception:
            return float(price)

    def min_order_notional(self, symbol: str) -> float | None:
        try:
            market = self._ex.market(symbol)
        except Exception:
            market = getattr(self._ex, "markets", {}).get(symbol, {})

        if not isinstance(market, dict):
            return None

        limits = market.get("limits") or {}
        cost = limits.get("cost") or {}
        min_cost = cost.get("min")

        if min_cost is not None:
            try:
                return float(min_cost)
            except (TypeError, ValueError):
                pass

        info = market.get("info") or {}
        filters = info.get("filters") if isinstance(info, dict) else None

        if isinstance(filters, list):
            for item in filters:
                if not isinstance(item, dict):
                    continue

                if item.get("filterType") in {"MIN_NOTIONAL", "NOTIONAL"}:
                    raw_value = (
                        item.get("minNotional")
                        or item.get("notional")
                        or item.get("minNotionalValue")
                    )

                    try:
                        return float(raw_value)
                    except (TypeError, ValueError):
                        continue

        return None


# ---------------------------------------------------------------------------
# Multi-exchange manager
# ---------------------------------------------------------------------------

    def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price=None,
    ):
        """
        Create an order through the wrapped exchange client.

        This intentionally propagates exchange exceptions upward so
        risk/failover layers can handle them correctly.
        """
        if not getattr(self, "execution_enabled", True):
            raise RuntimeError(
                f"Exchange {self.id} is connected for market data only; "
                "order execution is disabled because API credentials are missing."
            )

        return self._ex.create_order(
            symbol,
            order_type,
            side,
            amount,
            price,
        )

class ExchangeManager:
    """
    Manages connections to Binance, Bybit, and OKX simultaneously.

    Key features:
      - Routes buy orders to exchange with lowest ask price
      - Routes sell orders to exchange with highest bid price
      - Returns primary exchange (Binance) as fallback for OHLCV
      - All exchanges initialised in PAPER mode if cfg.mode == "PAPER"
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        self.exchanges: Dict[str, ExchangeWrapper] = {}
        self.primary: Optional[ExchangeWrapper] = None  # Binance
        self._init_exchanges()

    # ------------------------------------------------------------------

    def _init_exchanges(self) -> None:
        if not _HAS_CCXT:
            raise RuntimeError("ccxt is required. pip install ccxt")

        sandbox = self.cfg.mode == "PAPER"
        proxy = self.cfg.proxy or None

        definitions = [
            (
                "binance",
                {
                    "apiKey": self.cfg.binance_api_key,
                    "secret": self.cfg.binance_secret,
                    "options": {"defaultType": "spot"},
                },
            ),
            (
                "bybit",
                {
                    "apiKey": self.cfg.bybit_api_key,
                    "secret": self.cfg.bybit_secret,
                    "options": {"defaultType": "spot"},
                },
            ),
            (
                "okx",
                {
                    "apiKey": self.cfg.okx_api_key,
                    "secret": self.cfg.okx_secret,
                    "password": self.cfg.okx_passphrase,
                    "options": {"defaultType": "spot"},
                },
            ),
        ]

        enabled_raw = os.environ.get(
            "AEGIS_ENABLED_EXCHANGES",
            "binance,bybit,okx",
        )
        enabled_exchanges = {
            item.strip().lower()
            for item in enabled_raw.split(",")
            if item.strip()
        }

        if enabled_exchanges:
            definitions = [
                (ex_id, creds)
                for ex_id, creds in definitions
                if ex_id in enabled_exchanges
            ]

        for ex_id, creds in definitions:
            try:
                wrapper = self._build_exchange_wrapper(
                    ex_id=ex_id,
                    creds=creds,
                    sandbox=sandbox,
                    proxy=proxy,
                )

                self.exchanges[ex_id] = wrapper

            except Exception as exc:
                log.error(f"Failed to connect to {ex_id}: {exc}")

        if not self.exchanges:
            raise RuntimeError("No exchanges could be connected. Check credentials and network.")

        self.primary = self.exchanges.get("binance") or next(iter(self.exchanges.values()))
        log.info(f"Primary exchange: {self.primary.id}")

    def _has_execution_credentials(self, ex_id: str, creds: dict) -> bool:
        if not creds.get("apiKey") or not creds.get("secret"):
            return False

        if ex_id == "okx" and not creds.get("password"):
            return False

        return True

    def _public_market_data_creds(self, creds: dict) -> dict:
        public_creds = {}

        if "options" in creds:
            public_creds["options"] = dict(creds["options"])

        return public_creds

    def _make_exchange_object(
        self,
        ex_id: str,
        creds: dict,
        sandbox: bool,
        proxy: str | None,
    ):
        ex_class = getattr(ccxt, ex_id)
        kwargs = dict(creds)

        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}

        obj = ex_class(kwargs)

        if sandbox:
            try:
                obj.set_sandbox_mode(True)
            except Exception:
                pass

        return obj

    def _build_exchange_wrapper(
        self,
        ex_id: str,
        creds: dict,
        sandbox: bool,
        proxy: str | None,
    ) -> ExchangeWrapper:
        has_credentials = self._has_execution_credentials(ex_id, creds)

        if has_credentials:
            try:
                obj = self._make_exchange_object(
                    ex_id=ex_id,
                    creds=creds,
                    sandbox=sandbox,
                    proxy=proxy,
                )

                obj.load_markets()

                wrapper = ExchangeWrapper(ex_id, obj, self.cfg)
                wrapper.execution_enabled = True

                log.info(
                    f"Exchange connected: {ex_id} "
                    f"(mode={self.cfg.mode}, execution_enabled=True)"
                )

                return wrapper

            except Exception as exc:
                log.warning(
                    "%s credentialed connection failed: %s. "
                    "Retrying as public market-data-only.",
                    ex_id,
                    exc,
                )

        public_creds = self._public_market_data_creds(creds)

        obj = self._make_exchange_object(
            ex_id=ex_id,
            creds=public_creds,
            sandbox=sandbox,
            proxy=proxy,
        )

        obj.load_markets()

        wrapper = ExchangeWrapper(ex_id, obj, self.cfg)
        wrapper.execution_enabled = False

        log.info(
            f"Exchange connected: {ex_id} "
            f"(mode={self.cfg.mode}, execution_enabled=False)"
        )

        return wrapper

    # ------------------------------------------------------------------
    # Best-price routing
    # ------------------------------------------------------------------

    def best_buy_exchange(self, symbol: str) -> ExchangeWrapper:
        """Return exchange with the lowest ask (best for buying)."""
        best: Optional[ExchangeWrapper] = None
        best_ask = float("inf")
        for ex in self.exchanges.values():
            ask = ex.get_best_ask(symbol)
            if ask and ask < best_ask:
                best_ask = ask
                best = ex
        return best or self.primary

    def best_sell_exchange(self, symbol: str) -> ExchangeWrapper:
        """Return exchange with the highest bid (best for selling)."""
        best: Optional[ExchangeWrapper] = None
        best_bid = 0.0
        for ex in self.exchanges.values():
            bid = ex.get_best_bid(symbol)
            if bid and bid > best_bid:
                best_bid = bid
                best = ex
        return best or self.primary

    def get_prices(self, symbol: str) -> Dict[str, Optional[float]]:
        """Return mid-price from each exchange for cross-exchange comparison."""
        prices = {}
        for name, ex in self.exchanges.items():
            try:
                ticker = ex.fetch_ticker(symbol)
                prices[name] = float(ticker.get("last", 0)) or None
            except Exception:
                prices[name] = None
        return prices

    # ------------------------------------------------------------------
    # Arbitrage spread detection
    # ------------------------------------------------------------------

    def detect_arbitrage(self, symbol: str) -> Optional[dict]:
        """
        Check if there is a profitable arbitrage spread between exchanges.
        Returns dict with details if spread > 0.15%, else None.
        """
        MIN_SPREAD = 0.0015  # 0.15% minimum (covers fees)
        asks: Dict[str, float] = {}
        bids: Dict[str, float] = {}

        for name, ex in self.exchanges.items():
            ask = ex.get_best_ask(symbol)
            bid = ex.get_best_bid(symbol)
            if ask:
                asks[name] = ask
            if bid:
                bids[name] = bid

        if len(asks) < 2 or len(bids) < 2:
            return None

        cheapest_ask_ex = min(asks, key=asks.get)
        highest_bid_ex = max(bids, key=bids.get)

        if cheapest_ask_ex == highest_bid_ex:
            return None

        cheap_ask = asks[cheapest_ask_ex]
        high_bid = bids[highest_bid_ex]
        spread_pct = (high_bid - cheap_ask) / cheap_ask

        if spread_pct > MIN_SPREAD:
            return {
                "buy_exchange": cheapest_ask_ex,
                "sell_exchange": highest_bid_ex,
                "buy_price": cheap_ask,
                "sell_price": high_bid,
                "spread_pct": spread_pct,
                "symbol": symbol,
            }
        return None

    # ------------------------------------------------------------------
    # Aggregate balance (sum across all exchanges)
    # ------------------------------------------------------------------

    def get_total_usdt_balance(self) -> float:
        """
        In LIVE mode: sum USDT free balance across all connected exchanges.
        In PAPER mode: returns 0 (caller maintains paper balance).
        """
        if self.cfg.mode != "LIVE":
            return 0.0
        total = 0.0
        for name, ex in self.exchanges.items():
            try:
                bal = ex.fetch_balance()
                total += float(bal.get("USDT", {}).get("free", 0))
            except Exception as exc:
                log.warning(f"Balance fetch failed for {name}: {exc}")
        return total

    # ------------------------------------------------------------------
    # Startup reconciliation
    # ------------------------------------------------------------------

    def reconcile_all_open_orders(self, watchlist: List[str]) -> None:
        """Cancel any orphaned AEGIS orders left from a prior session."""
        if self.cfg.mode != "LIVE":
            return
        for name, ex in self.exchanges.items():
            for symbol in watchlist:
                try:
                    open_orders = ex.fetch_open_orders(symbol)
                    for order in open_orders:
                        cid = order.get("clientOrderId", "")
                        if cid.startswith("AEGIS-"):
                            log.warning(
                                f"[{name}] Cancelling orphaned order {order['id']} " f"for {symbol}"
                            )
                            ex.cancel_order(order["id"], symbol)
                except Exception as exc:
                    log.debug(f"[{name}] reconcile skip {symbol}: {exc}")

    # ------------------------------------------------------------------
    # Symbol availability check
    # ------------------------------------------------------------------

    def symbol_available(self, symbol: str, exchange_id: str = "binance") -> bool:
        ex = self.exchanges.get(exchange_id) or self.primary
        try:
            markets = ex._ex.markets
            return symbol in markets
        except Exception:
            return False

