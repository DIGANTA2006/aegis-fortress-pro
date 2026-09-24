"""
execution.py  –  AEGIS PRO v2
Order execution engine with:
  - Limit order placement at touch price
  - Every-2s price adjustment if unfilled
  - 10s timeout → fallback to market order
  - UUID client order IDs for idempotency
  - Slippage recording to RiskManager
"""

import logging
import threading
import time
import uuid
from typing import Optional

from config import AegisConfig
from risk import RiskManager
from utils import retry

log = logging.getLogger("aegis.execution")


class ExecutionEngine:
    """
    Handles all order placement and fill verification.
    Works in both PAPER and LIVE mode.
    """

    def __init__(self, exchange, cfg: AegisConfig, risk: RiskManager):
        self.exchange = exchange
        self.cfg = cfg
        self.risk = risk
        self._api_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public: buy entry
    # ------------------------------------------------------------------

    def execute_buy(
        self,
        symbol: str,
        amount: float,
        expected_price: float,
    ) -> Optional[dict]:
        """
        Execute a buy order.
        In LIVE mode: tries limit order first, falls back to market.
        In PAPER mode: simulates fill with slippage.
        Returns order result dict or None on failure.
        """
        if self.cfg.mode == "PAPER":
            return self._paper_fill(symbol, "buy", amount, expected_price)
        if self.cfg.live_confirm != "YES_I_ACCEPT_THE_RISK":
            log.error("Live trading requires live_confirm = 'YES_I_ACCEPT_THE_RISK'")
            return None
        return self._live_order(symbol, "buy", amount, expected_price)

    # ------------------------------------------------------------------
    # Public: sell exit
    # ------------------------------------------------------------------

    def execute_sell(
        self,
        symbol: str,
        amount: float,
        expected_price: float,
        reason: str = "EXIT",
    ) -> Optional[dict]:
        """
        Execute a sell order.
        Uses market order for exits to ensure fill (slippage > missed fill).
        """
        if self.cfg.mode == "PAPER":
            return self._paper_fill(symbol, "sell", amount, expected_price)
        if self.cfg.live_confirm != "YES_I_ACCEPT_THE_RISK":
            return None
        # Exits always market to guarantee fill
        return self._live_market_order(symbol, "sell", amount, reason=reason)

    # ------------------------------------------------------------------
    # Internal: PAPER mode
    # ------------------------------------------------------------------

    def _paper_fill(self, symbol: str, side: str, amount: float, expected_price: float) -> dict:
        slip = self.cfg.sim_slippage
        if side == "buy":
            actual_price = expected_price * (1 + slip)
        else:
            actual_price = expected_price * (1 - slip)
        fee_rate = 0.001
        cost = actual_price * amount
        fee = cost * fee_rate

        self.risk.record_slippage(symbol, expected_price, actual_price)

        return {
            "id": f"PAPER-{uuid.uuid4().hex[:8]}",
            "symbol": symbol,
            "side": side,
            "filled": amount,
            "average": actual_price,
            "cost": cost,
            "fee": {"cost": fee, "currency": "USDT"},
            "status": "closed",
        }

    # ------------------------------------------------------------------
    # Internal: LIVE limit → market fallback
    # ------------------------------------------------------------------

    def _live_order(
        self, symbol: str, side: str, amount: float, expected_price: float
    ) -> Optional[dict]:
        """
        Post a limit order at touch price.
        Poll every limit_adjust_secs; cancel and reprice if not filled.
        After limit_cancel_secs total, cancel and submit market.
        """
        deadline = time.time() + self.cfg.limit_cancel_secs
        order_id: Optional[str] = None

        while time.time() < deadline:
            # ---- Get fresh touch price ----
            touch_price = self._get_touch_price(symbol, side)
            if touch_price is None:
                break

            if order_id is not None:
                # Cancel existing limit order before repricing
                self._cancel_order(order_id, symbol)
                order_id = None

            # ---- Place limit order ----
            new_client_id = f"AEGIS-{uuid.uuid4().hex[:12]}"
            limit_result = self._place_limit_order(symbol, side, amount, touch_price, new_client_id)
            if limit_result is None:
                break

            order_id = limit_result.get("id")
            log.info(
                f"Limit {side.upper()} {symbol} qty={amount:.6g} "
                f"@ {touch_price:.6g} [id={order_id}]"
            )

            # ---- Poll for fill ----
            adjust_deadline = time.time() + self.cfg.limit_adjust_secs
            while time.time() < adjust_deadline and time.time() < deadline:
                time.sleep(0.25)
                status = self._check_order(order_id, symbol)
                if status is None:
                    break
                if status.get("status") in ("closed", "filled"):
                    log.info(
                        f"Limit order filled: {symbol} {side} "
                        f"@ {status.get('average', touch_price):.6g}"
                    )
                    self.risk.record_slippage(
                        symbol, expected_price, float(status.get("average", touch_price))
                    )
                    return status
                if status.get("status") == "canceled":
                    order_id = None
                    break

        # ---- Timeout: cancel limit and submit market ----
        if order_id:
            self._cancel_order(order_id, symbol)

        log.warning(f"Limit order timeout for {symbol}. Falling back to market.")
        return self._live_market_order(symbol, side, amount, reason="limit_fallback")

    # ------------------------------------------------------------------

    def _live_market_order(
        self, symbol: str, side: str, amount: float, reason: str = ""
    ) -> Optional[dict]:

        try:
            with self._api_lock:
                if side == "buy":
                    order = self.exchange.create_market_buy_order(
                        symbol, float(amount), {"clientOrderId": client_id}
                    )
                else:
                    order = self.exchange.create_market_sell_order(
                        symbol, float(amount), {"clientOrderId": client_id}
                    )
            time.sleep(0.5)
            # Verify fill
            order = self._check_order(order["id"], symbol) or order
            log.info(
                f"Market {side.upper()} {symbol} qty={amount:.6g} "
                f"@ {order.get('average', 'n/a')!s} [{reason}]"
            )
            return order
        except Exception as exc:
            log.error(f"Market order failed ({symbol} {side}): {exc}")
            return None

    # ------------------------------------------------------------------

    def _place_limit_order(
        self, symbol: str, side: str, amount: float, price: float, client_id: str
    ) -> Optional[dict]:
        try:
            with self._api_lock:
                if side == "buy":
                    order = self.exchange.create_limit_buy_order(
                        symbol, float(amount), float(price), {"clientOrderId": client_id}
                    )
                else:
                    order = self.exchange.create_limit_sell_order(
                        symbol, float(amount), float(price), {"clientOrderId": client_id}
                    )
            return order
        except Exception as exc:
            log.error(f"Limit order placement failed ({symbol}): {exc}")
            return None

    def _cancel_order(self, order_id: str, symbol: str) -> None:
        try:
            with self._api_lock:
                self.exchange.cancel_order(order_id, symbol)
        except Exception as exc:
            log.warning(f"Cancel order {order_id} failed: {exc}")

    @retry(max_attempts=3, base_delay=0.5)
    def _check_order(self, order_id: str, symbol: str) -> Optional[dict]:
        with self._api_lock:
            return self.exchange.fetch_order(order_id, symbol)

    def _get_touch_price(self, symbol: str, side: str) -> Optional[float]:
        """Return best bid (sell) or best ask (buy) from order book."""
        try:
            ob = self.exchange.fetch_order_book(symbol, limit=1)
            if side == "buy" and ob.get("asks"):
                return float(ob["asks"][0][0])
            if side == "sell" and ob.get("bids"):
                return float(ob["bids"][0][0])
        except Exception as exc:
            log.warning(f"Order book fetch failed ({symbol}): {exc}")
        return None

    # ------------------------------------------------------------------
    # Open-order reconciliation on startup
    # ------------------------------------------------------------------

    def reconcile_open_orders(self, watchlist: list) -> None:
        """
        On startup, cancel any orphaned open orders from a previous session.
        """
        if self.cfg.mode != "LIVE":
            return
        log.info("Reconciling open orders on startup...")
        for symbol in watchlist:
            try:
                open_orders = self.exchange.fetch_open_orders(symbol)
                for order in open_orders:
                    if order.get("clientOrderId", "").startswith("AEGIS-"):
                        log.warning(f"Cancelling orphaned order {order['id']} for {symbol}")
                        self._cancel_order(order["id"], symbol)
            except Exception as exc:
                log.warning(f"Could not reconcile orders for {symbol}: {exc}")
