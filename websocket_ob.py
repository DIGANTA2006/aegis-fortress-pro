"""
websocket_ob.py  -  AEGIS PRO v2
Real-time L2 order book via ccxt.pro WebSocket streams.

Maintains a local order book for up to 20 symbols simultaneously.
Falls back gracefully to REST polling if ccxt.pro is unavailable.

Usage:
    ob_manager = OrderBookManager(cfg)
    await ob_manager.start(watchlist)        # in async context
    book = ob_manager.get_book("BTC/USDT")  # thread-safe snapshot
    ob_manager.stop()
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import AegisConfig

log = logging.getLogger("aegis.websocket_ob")

# ---------------------------------------------------------------------------
# Optional ccxt.pro import
# ---------------------------------------------------------------------------
try:
    import ccxt.pro as ccxtpro

    _HAS_CCXT_PRO = True
except ImportError:
    _HAS_CCXT_PRO = False
    log.warning(
        "ccxt.pro not installed. WebSocket order book disabled. "
        "Falling back to REST. Install with: pip install ccxt[async_support]"
    )


# ---------------------------------------------------------------------------
# Book snapshot dataclass
# ---------------------------------------------------------------------------


@dataclass
class OrderBookSnapshot:
    symbol: str
    bids: List[Tuple[float, float]] = field(default_factory=list)  # (price, qty)
    asks: List[Tuple[float, float]] = field(default_factory=list)
    timestamp: float = 0.0
    exchange: str = "binance"

    @property
    def best_bid(self) -> Optional[float]:
        return float(self.bids[0][0]) if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return float(self.asks[0][0]) if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        if mid and self.spread:
            return self.spread / mid
        return 0.0

    def bid_volume(self, depth: int = 10) -> float:
        return sum(b[1] for b in self.bids[:depth])

    def ask_volume(self, depth: int = 10) -> float:
        return sum(a[1] for a in self.asks[:depth])

    def imbalance(self, depth: int = 10) -> float:
        """Bid/ask volume ratio. >1 = more buying pressure."""
        av = self.ask_volume(depth)
        return self.bid_volume(depth) / av if av > 0 else 1.0

    def bid_depth_ratio(self, depth: int = 10) -> float:
        total = self.bid_volume(depth) + self.ask_volume(depth)
        return self.bid_volume(depth) / total if total > 0 else 0.5

    def vwap_spread(self, depth: int = 5) -> float:
        """Volume-weighted average spread across top N levels."""
        if not self.bids or not self.asks:
            return 0.0
        total_w = 0.0
        w_spread = 0.0
        for i in range(min(depth, len(self.bids), len(self.asks))):
            bp, bq = self.bids[i]
            ap, aq = self.asks[i]
            w = (bq + aq) / 2
            w_spread += (ap - bp) * w
            total_w += w
        return w_spread / total_w if total_w > 0 else 0.0

    def order_flow_toxicity(self) -> float:
        """
        Simplified VPIN proxy: large imbalance signals informed order flow.
        Returns 0-1 where 1 = highly toxic (one-sided).
        """
        imb = self.imbalance()
        return abs(imb - 1.0) / max(imb, 1.0 / max(imb, 1e-6))

    def price_impact(self, side: str, usd_qty: float) -> float:
        """
        Estimate market-impact slippage in % for a market order of usd_qty.
        side: 'buy' (walks up asks) or 'sell' (walks down bids).
        """
        mid = self.mid
        if not mid:
            return 0.0
        levels = self.asks if side == "buy" else self.bids
        remaining = usd_qty
        wsum = 0.0
        for price, qty in levels:
            fill = min(remaining, qty * price)
            wsum += fill * price
            remaining -= fill
            if remaining <= 0:
                break
        if remaining > 0:
            return 0.02  # can't fill - huge impact
        avg_price = wsum / usd_qty
        if side == "buy":
            return (avg_price - mid) / mid
        else:
            return (mid - avg_price) / mid

    def to_feature_dict(self) -> dict:
        """Return all OB metrics as a flat dict for the feature engine."""
        return {
            "ob_imbalance": self.imbalance(),
            "bid_depth_ratio": self.bid_depth_ratio(),
            "ask_depth_ratio": 1.0 - self.bid_depth_ratio(),
            "spread_pct": self.spread_pct,
            "vwap_spread": self.vwap_spread(),
            "ob_toxicity": self.order_flow_toxicity(),
            "price_impact_buy": self.price_impact("buy", 1000.0),
            "price_impact_sell": self.price_impact("sell", 1000.0),
        }


# ---------------------------------------------------------------------------
# Order book manager
# ---------------------------------------------------------------------------


class OrderBookManager:
    """
    Manages WebSocket order book streams for multiple symbols.

    Runs an asyncio event loop in a dedicated daemon thread.
    Thread-safe snapshot access via get_book().
    """

    BOOK_DEPTH = 20  # levels to maintain
    STALE_SECS = 10  # mark book stale if not updated within N seconds

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        self._books: Dict[str, OrderBookSnapshot] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._exchange = None

    # ------------------------------------------------------------------
    # Public API (thread-safe)
    # ------------------------------------------------------------------

    def get_book(self, symbol: str) -> Optional[OrderBookSnapshot]:
        """Return the latest book snapshot, or None if stale/unavailable."""
        with self._lock:
            book = self._books.get(symbol)
        if book is None:
            return None
        if time.time() - book.timestamp > self.STALE_SECS:
            return None  # stale
        return book

    def get_ob_features(self, symbol: str) -> dict:
        """Return feature dict; falls back to neutral defaults if unavailable."""
        book = self.get_book(symbol)
        if book:
            return book.to_feature_dict()
        return {
            "ob_imbalance": 1.0,
            "bid_depth_ratio": 0.5,
            "ask_depth_ratio": 0.5,
            "spread_pct": 0.001,
            "vwap_spread": 0.0,
            "ob_toxicity": 0.0,
            "price_impact_buy": 0.001,
            "price_impact_sell": 0.001,
        }

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def start(self, symbols: List[str]) -> None:
        """Start the WebSocket loop in a background daemon thread."""
        if not _HAS_CCXT_PRO:
            log.info("OrderBookManager: ccxt.pro unavailable, using REST fallback.")
            return

        self._symbols = symbols[:20]  # cap at 20
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(symbols,),
            daemon=True,
            name="ob-ws-loop",
        )
        self._thread.start()
        log.info(f"OrderBookManager started for {len(self._symbols)} symbols.")

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_exchange(), self._loop)

    # ------------------------------------------------------------------
    # Async internals
    # ------------------------------------------------------------------

    def _run_loop(self, symbols: List[str]) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._stream_all(symbols))
        except Exception as exc:
            log.error(f"OrderBookManager loop crashed: {exc}")
        finally:
            self._loop.close()
            self._running = False

    async def _stream_all(self, symbols: List[str]) -> None:
        """Launch one watcher coroutine per symbol, plus a reconnect supervisor."""
        self._exchange = ccxtpro.binance(
            {
                "apiKey": self.cfg.binance_api_key or "",
                "secret": self.cfg.binance_secret or "",
                "options": {"defaultType": "spot"},
            }
        )
        try:
            tasks = [self._watch_symbol(sym) for sym in symbols]
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._close_exchange()

    async def _watch_symbol(self, symbol: str) -> None:
        """
        Continuously watch a single symbol's order book.
        On any error, waits 5s and reconnects.
        """
        while self._running:
            try:
                ob = await self._exchange.watch_order_book(symbol, limit=self.BOOK_DEPTH)
                snap = OrderBookSnapshot(
                    symbol=symbol,
                    bids=[(float(p), float(q)) for p, q in ob["bids"][: self.BOOK_DEPTH]],
                    asks=[(float(p), float(q)) for p, q in ob["asks"][: self.BOOK_DEPTH]],
                    timestamp=time.time(),
                    exchange="binance",
                )
                with self._lock:
                    self._books[symbol] = snap
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning(f"OB stream error ({symbol}): {exc}. Reconnecting in 5s.")
                await asyncio.sleep(5)

    async def _close_exchange(self) -> None:
        if self._exchange:
            try:
                await self._exchange.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # REST fallback: bulk-update all books synchronously
    # ------------------------------------------------------------------

    def rest_update(self, rest_exchange, symbol: str) -> None:
        """
        Manually populate book from a REST fetch_order_book call.
        Used when WebSocket is unavailable.
        """
        try:
            ob = rest_exchange.fetch_order_book(symbol, limit=self.BOOK_DEPTH)
            snap = OrderBookSnapshot(
                symbol=symbol,
                bids=[(float(p), float(q)) for p, q in ob["bids"][: self.BOOK_DEPTH]],
                asks=[(float(p), float(q)) for p, q in ob["asks"][: self.BOOK_DEPTH]],
                timestamp=time.time(),
                exchange="binance",
            )
            with self._lock:
                self._books[symbol] = snap
        except Exception as exc:
            log.debug(f"REST OB update failed ({symbol}): {exc}")
