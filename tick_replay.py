"""
tick_replay.py  -  AEGIS PRO v2
Tick-level replay engine: reads raw ticks from TickDB and simulates fills
with realistic latency, partial fills, and queue position modelling.

Wires into backtest.py via TickReplayBacktester which extends Backtester.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest import Backtester, BacktestResult
from config import AegisConfig
from db import TickDB
from models import SignalFusion, XGBSignalModel

log = logging.getLogger("aegis.tick_replay")


# ---------------------------------------------------------------------------
# Simulated fill model
# ---------------------------------------------------------------------------


@dataclass
class SimFill:
    ts_ms: int
    price: float
    qty: float
    side: str  # "buy" | "sell"
    latency_ms: float
    queue_pos: int  # estimated queue position at the price level
    partial: bool

    @property
    def slippage_pct(self) -> float:
        return 0.0  # set externally relative to expected price


class TickFillSimulator:
    """
    Models order fill from a sequence of ticks.

    For a limit order at price P:
      - Scans forward through ticks
      - Fills when ticks trade at or through P
      - Models queue position: orders placed earlier fill first
      - Applies realistic latency (5-50ms exchange round-trip)

    For a market order:
      - Fills at next available tick price + slippage
    """

    LATENCY_MS_MEAN = 20.0  # ms round-trip to exchange
    LATENCY_MS_STD = 8.0
    MAX_QUEUE_DEPTH = 50  # assume max 50 units ahead in queue

    def simulate_market_fill(
        self,
        ticks: List[dict],
        side: str,
        qty: float,
        request_ts_ms: int,
    ) -> Optional[SimFill]:
        """Fill at next available tick after latency."""
        latency = max(1.0, np.random.normal(self.LATENCY_MS_MEAN, self.LATENCY_MS_STD))
        target_ts = request_ts_ms + latency

        for tick in ticks:
            if tick["ts"] >= target_ts:
                slip = np.random.uniform(0.0001, 0.0008)  # 0.01-0.08% slippage
                price = tick["price"] * (1 + slip if side == "buy" else 1 - slip)
                return SimFill(
                    ts_ms=tick["ts"],
                    price=price,
                    qty=qty,
                    side=side,
                    latency_ms=latency,
                    queue_pos=0,
                    partial=False,
                )
        return None

    def simulate_limit_fill(
        self,
        ticks: List[dict],
        side: str,
        qty: float,
        limit_price: float,
        request_ts_ms: int,
        timeout_ms: float = 10_000,
    ) -> Optional[SimFill]:
        """
        Try to fill a limit order. Returns None if never filled within timeout.
        Fills when a tick trades at or through our limit price.
        """
        latency = max(1.0, np.random.normal(self.LATENCY_MS_MEAN, self.LATENCY_MS_STD))
        placed_ts = request_ts_ms + latency
        expire_ts = placed_ts + timeout_ms
        queue_pos = np.random.randint(0, self.MAX_QUEUE_DEPTH)
        units_ahead = queue_pos * (qty * 0.2)  # rough estimate

        volume_seen = 0.0
        for tick in ticks:
            if tick["ts"] < placed_ts:
                continue
            if tick["ts"] > expire_ts:
                break

            # Fill condition: tick price at or through our limit
            fills_buy = side == "buy" and tick["price"] <= limit_price
            fills_sell = side == "sell" and tick["price"] >= limit_price

            if fills_buy or fills_sell:
                volume_seen += tick["qty"]
                if volume_seen >= units_ahead:
                    return SimFill(
                        ts_ms=tick["ts"],
                        price=limit_price,  # limit orders fill at limit price
                        qty=qty,
                        side=side,
                        latency_ms=latency,
                        queue_pos=queue_pos,
                        partial=False,
                    )
        return None  # timed out unfilled


# ---------------------------------------------------------------------------
# Tick replay backtester
# ---------------------------------------------------------------------------


class TickReplayBacktester(Backtester):
    """
    Extends Backtester with tick-level fill simulation.

    Instead of filling at next-bar open, uses actual tick data for
    realistic slippage and fill latency modelling.

    Falls back to bar-level fills if tick data is unavailable.
    """

    TAKER_FEE = 0.001
    MAKER_FEE = 0.0002  # limit orders get maker rebate on most exchanges
    USE_LIMIT_ORDERS = True

    def __init__(
        self,
        cfg: AegisConfig,
        tick_db: TickDB,
        ml_model: Optional[XGBSignalModel] = None,
        signal_fusion: Optional[SignalFusion] = None,
    ):
        super().__init__(cfg, ml_model, signal_fusion)
        self.tick_db = tick_db
        self.fill_sim = TickFillSimulator()

    def _get_ticks_for_bar(self, symbol: str, bar_ts_ms: int, next_bar_ts_ms: int) -> List[dict]:
        """Fetch raw ticks for a single 15m bar window."""
        return self.tick_db.get_ticks(symbol, bar_ts_ms, limit=2000)

    def run_tick_level(
        self,
        df_15m: pd.DataFrame,
        symbol: str,
        initial_capital: float = 10_000.0,
        df_1h: Optional[pd.DataFrame] = None,
        df_4h: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """
        Full tick-level backtest.  Falls back to bar-level if no tick data.
        """
        # Check if tick data is available for this symbol
        test_ts = (
            int(df_15m.index[0].timestamp() * 1000) if hasattr(df_15m.index[0], "timestamp") else 0
        )
        test_ticks = self.tick_db.get_ticks(symbol, test_ts, limit=5)

        if not test_ticks:
            log.info(f"No tick data for {symbol}. Using bar-level backtest.")
            return self.run(df_15m, symbol, initial_capital, df_1h, df_4h)

        log.info(f"Tick-level replay: {symbol} ({len(df_15m)} bars)")
        result = BacktestResult(symbol=symbol)
        equity = initial_capital
        peak_equity = equity
        bar_returns: List[float] = []
        gross_wins = gross_losses = 0.0

        warmup = 210
        if len(df_15m) < warmup + 20:
            return result

        position = None

        for i in range(warmup, len(df_15m) - 1):
            df_slice = df_15m.iloc[: i + 1]
            bar = df_15m.iloc[i]
            next_bar = df_15m.iloc[i + 1]

            # Get bar timestamps
            bar_ts_ms = int(bar.name.timestamp() * 1000) if hasattr(bar.name, "timestamp") else 0
            next_bar_ts_ms = (
                int(next_bar.name.timestamp() * 1000)
                if hasattr(next_bar.name, "timestamp")
                else bar_ts_ms + 900_000
            )
            bar_ticks = self._get_ticks_for_bar(symbol, bar_ts_ms, next_bar_ts_ms)

            # ---- Manage open position with tick fills ----
            if position is not None:
                exit_price, exit_reason = self._check_exit_tick(position, bar, bar_ticks)
                if exit_price is not None:
                    fee = exit_price * position["qty"] * self.MAKER_FEE
                    pnl = (
                        (exit_price - position["entry_price"]) * position["qty"]
                        - fee
                        - position["entry_fee"]
                    )
                    equity += pnl

                    r_mult = pnl / max(position["risk_dollars"], 1e-6)
                    if pnl > 0:
                        result.wins += 1
                        gross_wins += pnl
                        result.avg_win_r += r_mult
                    else:
                        result.losses += 1
                        gross_losses += abs(pnl)
                        result.avg_loss_r += abs(r_mult)

                    result.total_trades += 1
                    bar_returns.append(pnl / max(equity, 1))
                    peak_equity = max(peak_equity, equity)
                    dd = (peak_equity - equity) / peak_equity * 100
                    result.max_drawdown_pct = max(result.max_drawdown_pct, dd)
                    result.trades.append({"i": i, "action": exit_reason, "pnl": pnl, "r": r_mult})
                    position = None

            # ---- Look for entry ----
            if position is None and i < len(df_15m) - 2:

                row = self.fe.compute(df_slice, df_1h=df_1h, df_4h=df_4h, ob=None)
                if row is None:
                    continue

                from data import validate_signal_conditions

                sig = validate_signal_conditions(row, self.cfg, True, symbol)
                if sig is None:
                    continue

                ml_prob = self.ml.predict(row) if self.ml and self.ml.model else 0.5
                if ml_prob < self.cfg.ml_prob_threshold:
                    continue

                atr = float(row.get("atr", float(bar["c"]) * 0.01))
                price = float(bar["c"])

                # Use tick-level fill simulation
                request_ts = bar_ts_ms + 100  # 100ms signal processing delay
                if self.USE_LIMIT_ORDERS and bar_ticks:
                    # Post limit at mid-price
                    touch = price * 0.9999
                    fill = self.fill_sim.simulate_limit_fill(
                        bar_ticks, "buy", 1.0, touch, request_ts
                    )
                    if fill is None:
                        # Fall back to market
                        fill = self.fill_sim.simulate_market_fill(bar_ticks, "buy", 1.0, request_ts)
                    fee_rate = self.MAKER_FEE if (fill and not fill.partial) else self.TAKER_FEE
                else:
                    fill = self.fill_sim.simulate_market_fill(
                        bar_ticks or [], "buy", 1.0, request_ts
                    )
                    fee_rate = self.TAKER_FEE

                entry_price = fill.price if fill else price * 1.0005
                risk_dollars = equity * self.cfg.base_risk_per_trade
                stop_dist = self.cfg.atr_stop_mult * atr
                qty = risk_dollars / stop_dist if stop_dist > 0 else 0
                cost = qty * entry_price
                fee = cost * fee_rate

                if cost > equity * 0.95 or cost < 10:
                    continue

                position = {
                    "entry_price": entry_price,
                    "qty": qty,
                    "stop_loss": entry_price - stop_dist,
                    "tp1": entry_price + self.cfg.atr_tp1_mult * atr,
                    "tp2": entry_price + self.cfg.atr_tp2_mult * atr,
                    "atr": atr,
                    "risk_dollars": risk_dollars,
                    "entry_fee": fee,
                    "tp1_taken": False,
                    "tp2_taken": False,
                    "entry_bar": i,
                }
                equity -= fee

            result.equity_curve.append(equity)

        # Close any open position
        if position is not None:
            last_price = float(df_15m.iloc[-1]["c"])
            fee = last_price * position["qty"] * self.TAKER_FEE
            pnl = (last_price - position["entry_price"]) * position["qty"] - fee
            equity += pnl
            result.total_trades += 1
            if pnl > 0:
                result.wins += 1
            else:
                result.losses += 1

        # Statistics
        result.net_pnl = equity - initial_capital
        result.profit_factor = gross_wins / max(gross_losses, 1e-10)
        result.win_rate = result.wins / max(result.total_trades, 1)
        if result.wins > 0:
            result.avg_win_r /= result.wins
        if result.losses > 0:
            result.avg_loss_r /= result.losses
        result.expectancy = (
            result.win_rate * result.avg_win_r - (1 - result.win_rate) * result.avg_loss_r
        )

        result.sharpe = self._sharpe(bar_returns)
        return result

    def _check_exit_tick(
        self, pos: dict, bar: pd.Series, ticks: List[dict]
    ) -> Tuple[Optional[float], str]:
        """
        Check exits using intra-bar tick data for precise fill prices.
        """
        atr = pos["atr"]

        # Sort ticks by time
        for tick in sorted(ticks, key=lambda t: t["ts"]):
            p = tick["price"]

            # Stop hit
            if p <= pos["stop_loss"]:
                return p, "STOP"

            # TP1
            if not pos["tp1_taken"] and p >= pos["tp1"]:
                pos["tp1_taken"] = True
                pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])

            # TP2
            if pos["tp1_taken"] and not pos["tp2_taken"] and p >= pos["tp2"]:
                pos["tp2_taken"] = True

            # Trailing stop after TP1
            if pos["tp1_taken"]:
                trail = p - 2.0 * atr
                pos["stop_loss"] = max(pos["stop_loss"], trail)
                if tick["price"] <= pos["stop_loss"]:
                    return pos["stop_loss"], "TRAIL_STOP"

        # Time stop: check at bar close

        return None, ""
