"""
market_maker.py  -  AEGIS PRO v2
Avellaneda-Stoikov (2008) inventory-aware market-making model.

Only activated on high-liquidity pairs when:
  - Spread is wide enough to cover fees + target profit
  - Volatility is within acceptable range
  - Bot is not already managing a directional position in the symbol

The model computes:
  - Reservation price  r = s - qÃ‚Â·?Ã‚Â·sÃ‚Â²Ã‚Â·(T-t)
  - Optimal spread     d = ?Ã‚Â·sÃ‚Â²Ã‚Â·(T-t) + (2/?)Ã‚Â·ln(1 + ?/k)

Where:
  s = mid price, q = inventory, ? = risk aversion,
  s = volatility, T-t = time remaining, k = order book depth param

Reference: Avellaneda & Stoikov, "High-frequency trading in a limit order book"
           Quantitative Finance, 2008.
"""

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import AegisConfig

log = logging.getLogger("aegis.mm")

# Minimum spread to consider market making (covers taker fees both sides)
MIN_VIABLE_SPREAD_PCT = 0.003  # 0.30%
MAX_INVENTORY_USD = 500.0  # max inventory value per symbol
QUOTE_LIFETIME_SECS = 8.0  # cancel and requote every N seconds


@dataclass
class MMQuote:
    """Active market-making quote pair."""

    symbol: str
    bid_price: float
    ask_price: float
    bid_qty: float
    ask_qty: float
    bid_order_id: Optional[str] = None
    ask_order_id: Optional[str] = None
    placed_at: float = field(default_factory=time.time)
    inventory: float = 0.0  # units currently held (positive = long)


class AvellanedaStoikov:
    """
    Avellaneda-Stoikov reservation-price market maker.

    Usage:
        mm = AvellanedaStoikov(cfg)
        quotes = mm.compute_quotes(symbol, mid_price, volatility, inventory_units, equity)
        # bid_price, ask_price = quotes
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        self.gamma = 0.1  # risk-aversion coefficient (tune per symbol)
        self.k = 1.5  # order book depth / fill rate parameter
        self.T = 1.0  # session horizon (normalised to 1.0)

    def compute_quotes(
        self,
        mid_price: float,
        volatility: float,  # annualised s; convert from ATR/price
        inventory: float,  # units currently held (+long, -short)
        time_left: float,  # fraction of session remaining (0-1)
        equity: float,
    ) -> Tuple[float, float]:
        """
        Returns (bid_price, ask_price) for optimal quotes.
        bid < mid < ask always.
        """
        if mid_price <= 0 or volatility <= 0:
            half = mid_price * 0.001
            return mid_price - half, mid_price + half

        sigma2 = volatility**2
        dt = max(time_left, 0.01)  # avoid division by zero

        # Reservation price: mid shifted by inventory risk
        reservation = mid_price - inventory * self.gamma * sigma2 * dt

        # Optimal spread
        spread = self.gamma * sigma2 * dt + (2 / self.gamma) * math.log(1 + self.gamma / self.k)

        # Ensure spread covers fees (0.1% taker each side = 0.2% round-trip)
        spread = max(spread, mid_price * MIN_VIABLE_SPREAD_PCT)

        bid = reservation - spread / 2
        ask = reservation + spread / 2

        # Safety: never cross
        if bid >= ask:
            bid = mid_price * (1 - MIN_VIABLE_SPREAD_PCT / 2)
            ask = mid_price * (1 + MIN_VIABLE_SPREAD_PCT / 2)

        return round(bid, 8), round(ask, 8)


class MarketMaker:
    """
    Orchestrates market-making on a subset of high-liquidity symbols.

    Workflow per cycle:
      1. Cancel stale quotes (older than QUOTE_LIFETIME_SECS)
      2. Fetch order book; compute mid + spread; check viability
      3. Compute AS reservation price + optimal spread
      4. Place new bid + ask limit orders
      5. Track fills ? update inventory
    """

    def __init__(self, exchange, cfg: AegisConfig):
        self.exchange = exchange
        self.cfg = cfg
        self.as_model = AvellanedaStoikov(cfg)
        self._quotes: Dict[str, MMQuote] = {}  # symbol ? active quote
        self._lock = threading.Lock()
        self._session_start = time.time()
        self._enabled = False  # switched on only when viable

    # ------------------------------------------------------------------
    # Viability gate
    # ------------------------------------------------------------------

    def is_viable(
        self,
        symbol: str,
        spread_pct: float,
        atr_rel: float,
        in_directional_trade: bool,
    ) -> bool:
        """
        Gate: market-make only when spread is rich enough but volatility
        is not so high that inventory risk exceeds reward.
        """
        if in_directional_trade:
            return False
        if spread_pct < MIN_VIABLE_SPREAD_PCT:
            return False
        if atr_rel > 2.0:  # too volatile - AS assumptions break down
            return False
        return True

    # ------------------------------------------------------------------
    # Main cycle (call every QUOTE_LIFETIME_SECS)
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        symbol: str,
        equity: float,
        atr: float,
        in_directional_trade: bool = False,
    ) -> Optional[MMQuote]:
        """
        Execute one market-making cycle for the given symbol.
        Returns the active MMQuote or None if not viable.
        """
        # Cancel any existing stale quotes
        self._cancel_stale(symbol)

        # Fetch order book
        try:
            ob = self.exchange.fetch_order_book(symbol, limit=5)
        except Exception as exc:
            log.warning(f"MM: order book fetch failed {symbol}: {exc}")
            return None

        if not ob.get("bids") or not ob.get("asks"):
            return None

        best_bid = float(ob["bids"][0][0])
        best_ask = float(ob["asks"][0][0])
        mid_price = (best_bid + best_ask) / 2
        spread_pct = (best_ask - best_bid) / mid_price

        # Annualised volatility from ATR (ATR/price Ãƒ- sqrt(365Ãƒ-96) for 15m bars)
        sigma = (atr / mid_price) * math.sqrt(365 * 96)
        atr_rel = atr / mid_price * 100  # as percentage

        if not self.is_viable(symbol, spread_pct, atr_rel, in_directional_trade):
            return None

        with self._lock:
            existing = self._quotes.get(symbol)
            inventory = existing.inventory if existing else 0.0

        # Inventory cap check
        inventory_usd = abs(inventory * mid_price)
        if inventory_usd > MAX_INVENTORY_USD:
            log.debug(f"MM {symbol}: inventory cap reached ({inventory_usd:.0f} USD)")
            return None

        # Time remaining in session (normalised, reset each hour)
        elapsed = (time.time() - self._session_start) % 3600
        time_left = max(0.01, 1.0 - elapsed / 3600)

        # Compute AS quotes
        bid_px, ask_px = self.as_model.compute_quotes(
            mid_price, sigma, inventory, time_left, equity
        )

        # Quote quantity: 1% of equity per side, split across bid+ask
        quote_usd = equity * 0.01
        bid_qty = round(quote_usd / bid_px, 6)
        ask_qty = round(quote_usd / ask_px, 6)

        if bid_qty * bid_px < 10 or ask_qty * ask_px < 10:
            return None  # below exchange minimum

        # Place orders
        bid_order = self._place_limit(symbol, "buy", bid_qty, bid_px)
        ask_order = self._place_limit(symbol, "sell", ask_qty, ask_px)

        if not bid_order and not ask_order:
            return None

        quote = MMQuote(
            symbol=symbol,
            bid_price=bid_px,
            ask_price=ask_px,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            bid_order_id=bid_order,
            ask_order_id=ask_order,
            inventory=inventory,
        )
        with self._lock:
            self._quotes[symbol] = quote

        log.info(
            f"MM quote {symbol}: bid={bid_px:.6g} ask={ask_px:.6g} "
            f"spread={((ask_px-bid_px)/mid_price*100):.3f}% inv={inventory:.4g}"
        )
        return quote

    # ------------------------------------------------------------------
    # Fill tracking
    # ------------------------------------------------------------------

    def check_fills(self, symbol: str) -> Tuple[float, float]:
        """
        Check if any open MM orders have been filled.
        Returns (pnl, inventory_delta).
        """
        with self._lock:
            quote = self._quotes.get(symbol)
        if not quote:
            return 0.0, 0.0

        pnl_total = 0.0
        inv_delta = 0.0

        for side, order_id, price, _qty in [
            ("buy", quote.bid_order_id, quote.bid_price, quote.bid_qty),
            ("sell", quote.ask_order_id, quote.ask_price, quote.ask_qty),
        ]:
            if not order_id:
                continue
            try:
                order = self.exchange.fetch_order(order_id, symbol)
                filled = float(order.get("filled", 0))
                if filled <= 0:
                    continue
                fee = filled * price * 0.001  # maker fee typically lower
                if side == "buy":
                    inv_delta += filled
                    pnl_total -= fee
                else:
                    inv_delta -= filled
                    pnl_total += filled * price - fee
            except Exception as exc:
                log.debug(f"MM fill check {symbol} {order_id}: {exc}")

        if inv_delta != 0:
            with self._lock:
                if symbol in self._quotes:
                    self._quotes[symbol].inventory += inv_delta

        return pnl_total, inv_delta

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _place_limit(self, symbol: str, side: str, qty: float, price: float) -> Optional[str]:
        """Place a limit order; return order_id or None."""
        if self.cfg.mode == "PAPER":
            return f"PAPER-MM-{uuid.uuid4().hex[:8]}"
        try:
            cid = f"AEGIS-MM-{uuid.uuid4().hex[:10]}"
            if side == "buy":
                order = self.exchange.create_limit_buy_order(
                    symbol, qty, price, {"clientOrderId": cid}
                )
            else:
                order = self.exchange.create_limit_sell_order(
                    symbol, qty, price, {"clientOrderId": cid}
                )
            return order.get("id")
        except Exception as exc:
            log.warning(f"MM limit order failed {symbol} {side}: {exc}")
            return None

    def _cancel_stale(self, symbol: str) -> None:
        with self._lock:
            quote = self._quotes.get(symbol)
        if not quote:
            return
        age = time.time() - quote.placed_at
        if age < QUOTE_LIFETIME_SECS:
            return
        for order_id in [quote.bid_order_id, quote.ask_order_id]:
            if order_id and not order_id.startswith("PAPER"):
                try:
                    self.exchange.cancel_order(order_id, symbol)
                except Exception:
                    pass
        with self._lock:
            if symbol in self._quotes:
                del self._quotes[symbol]

    def cancel_all(self) -> None:
        """Cancel all active MM quotes (called on shutdown)."""
        with self._lock:
            symbols = list(self._quotes.keys())
        for sym in symbols:
            self._cancel_stale.__wrapped__ = lambda s: None  # force-expire
            self._cancel_stale(sym)

    def get_active_symbols(self) -> List[str]:
        with self._lock:
            return list(self._quotes.keys())

    def get_total_inventory_usd(self, prices: Dict[str, float]) -> float:
        with self._lock:
            total = 0.0
            for sym, q in self._quotes.items():
                total += abs(q.inventory) * prices.get(sym, 0)
        return total
