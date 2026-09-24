"""
backtest.py  –  AEGIS PRO v2
Event-driven backtesting engine.

Replays OHLCV bar-by-bar, applying:
  - Signal generation via FeatureEngine + validate_signal_conditions
  - ML model inference (if model loaded)
  - Realistic fills: market orders use next open + slippage
  - ATR-based stops, trailing stop, layered TPs
  - Time-based stop (exit after N bars without profit)
  - Full transaction costs (taker fee + spread slippage)

Output: BacktestResult with Sharpe, MaxDD, profit factor, trade log.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import AegisConfig
from data import FeatureEngine, validate_signal_conditions
from models import SignalFusion, XGBSignalModel

log = logging.getLogger("aegis.backtest")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    total_fees: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    expectancy: float = 0.0
    trades: List[dict] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    def meets_live_criteria(self) -> Tuple[bool, List[str]]:
        """Check if strategy passes the minimum thresholds for live deployment."""
        failures = []
        if self.sharpe < 1.5:
            failures.append(f"Sharpe {self.sharpe:.2f} < 1.5")
        if self.max_drawdown_pct > 15.0:
            failures.append(f"MaxDD {self.max_drawdown_pct:.1f}% > 15%")
        if self.profit_factor < 1.5:
            failures.append(f"ProfitFactor {self.profit_factor:.2f} < 1.5")
        if self.total_trades < 30:
            failures.append(f"Trades {self.total_trades} < 30 (need 500 for full validation)")
        return len(failures) == 0, failures

    def summary(self) -> str:
        ok, fails = self.meets_live_criteria()
        gate = "✅ PASS" if ok else f"❌ FAIL ({'; '.join(fails)})"
        return (
            f"=== Backtest: {self.symbol} ===\n"
            f"  Trades:        {self.total_trades}  "
            f"(W={self.wins}, L={self.losses}, WR={self.win_rate*100:.1f}%)\n"
            f"  Net PnL:       ${self.net_pnl:+.2f}\n"
            f"  Sharpe:        {self.sharpe:.3f}\n"
            f"  MaxDrawdown:   {self.max_drawdown_pct:.2f}%\n"
            f"  Profit Factor: {self.profit_factor:.3f}\n"
            f"  Avg Win R:     {self.avg_win_r:.3f}\n"
            f"  Avg Loss R:    {self.avg_loss_r:.3f}\n"
            f"  Expectancy:    {self.expectancy:.4f}\n"
            f"  Live Gate:     {gate}\n"
        )


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------


class Backtester:
    """
    Bar-by-bar simulation.

    Usage:
        bt = Backtester(cfg, ml_model, signal_fusion)
        result = bt.run(df_15m, df_1h, df_4h, symbol="BTC/USDT",
                        initial_capital=10000)
        print(result.summary())
    """

    TAKER_FEE = 0.001  # 0.1% per side
    SLIPPAGE = 0.0005  # 0.05% market impact per fill

    def __init__(
        self,
        cfg: AegisConfig,
        ml_model: Optional[XGBSignalModel] = None,
        signal_fusion: Optional[SignalFusion] = None,
    ):
        self.cfg = cfg
        self.fe = FeatureEngine(cfg)
        self.ml = ml_model
        self.fusion = signal_fusion

    # ------------------------------------------------------------------

    def run(
        self,
        df_15m: pd.DataFrame,
        symbol: str,
        initial_capital: float = 10_000.0,
        df_1h: Optional[pd.DataFrame] = None,
        df_4h: Optional[pd.DataFrame] = None,
        btc_bullish: bool = True,
    ) -> BacktestResult:
        result = BacktestResult(symbol=symbol)
        equity = initial_capital
        peak_equity = equity
        result.equity_curve.append(equity)

        bar_returns: List[float] = []
        gross_wins = 0.0
        gross_losses = 0.0

        # Warm-up: need at least 210 bars for features
        warmup = 210
        if len(df_15m) < warmup + 20:
            log.warning(f"Backtest {symbol}: not enough bars ({len(df_15m)} < {warmup+20})")
            return result

        position = None  # dict while in trade

        for i in range(warmup, len(df_15m) - 1):
            df_slice = df_15m.iloc[: i + 1]
            bar = df_15m.iloc[i]
            next_bar = df_15m.iloc[i + 1]
            current_price = float(bar["c"])
            next_open = float(next_bar["o"])

            # ---- Manage open position ----
            if position is not None:
                exit_price, exit_reason = self._check_exit(position, bar, i)
                if exit_price is not None:
                    equity, trade_pnl = self._close_position(
                        position, exit_price, exit_reason, equity
                    )
                    r_mult = trade_pnl / max(position["risk_dollars"], 1e-6)
                    result.trades.append(
                        {
                            "i": i,
                            "symbol": symbol,
                            "action": exit_reason,
                            "price": exit_price,
                            "pnl": trade_pnl,
                            "r": r_mult,
                        }
                    )
                    if trade_pnl > 0:
                        result.wins += 1
                        gross_wins += trade_pnl
                        result.avg_win_r += r_mult
                    else:
                        result.losses += 1
                        gross_losses += abs(trade_pnl)
                        result.avg_loss_r += abs(r_mult)
                    result.total_trades += 1
                    bar_returns.append(trade_pnl / max(equity, 1))
                    peak_equity = max(peak_equity, equity)
                    dd = (peak_equity - equity) / peak_equity * 100
                    result.max_drawdown_pct = max(result.max_drawdown_pct, dd)
                    position = None

            # ---- Look for entry ----
            if position is None and i < len(df_15m) - 2:
                row = self.fe.compute(df_slice, df_1h=df_1h, df_4h=df_4h, ob=None)
                if row is None:
                    continue

                sig = validate_signal_conditions(row, self.cfg, btc_bullish, symbol)
                if sig is None:
                    continue

                # ML filter
                ml_prob = 0.5
                if self.ml and self.ml.model is not None:
                    ml_prob = self.ml.predict(row)
                    if ml_prob < self.cfg.ml_prob_threshold:
                        continue

                fused = 0.65
                if self.fusion:
                    ob_imb = float(row.get("ob_imbalance", 1.0))
                    if math.isnan(ob_imb):
                        ob_imb = 1.0
                    fused = self.fusion.fuse(sig, ml_prob, ob_imb)
                    if fused < self.cfg.fused_threshold:
                        continue

                # Enter on next bar open + slippage
                entry_price = next_open * (1 + self.SLIPPAGE)
                atr = float(row.get("atr", current_price * 0.01))
                stop_dist = self.cfg.atr_stop_mult * atr
                risk_dollars = equity * self.cfg.base_risk_per_trade
                qty = risk_dollars / stop_dist if stop_dist > 0 else 0
                cost = qty * entry_price
                fee = cost * self.TAKER_FEE

                if cost > equity * 0.95 or cost < 10:
                    continue

                position = {
                    "entry_price": entry_price,
                    "qty": qty,
                    "initial_qty": qty,
                    "stop_loss": entry_price - stop_dist,
                    "tp1": entry_price + self.cfg.atr_tp1_mult * atr,
                    "tp2": entry_price + self.cfg.atr_tp2_mult * atr,
                    "atr": atr,
                    "risk_dollars": risk_dollars,
                    "entry_fee": fee,
                    "tp1_taken": False,
                    "tp2_taken": False,
                    "trail_active": False,
                    "entry_bar": i,
                    "signal_type": sig,
                }
                equity -= fee  # deduct entry fee

            result.equity_curve.append(equity)

        # Force-close any open position at last bar
        if position is not None:
            last_price = float(df_15m.iloc[-1]["c"])
            equity, pnl = self._close_position(position, last_price, "END", equity)
            if pnl > 0:
                result.wins += 1
                gross_wins += pnl
            else:
                result.losses += 1
                gross_losses += abs(pnl)
            result.total_trades += 1
            result.trades.append({"i": len(df_15m) - 1, "action": "END", "pnl": pnl})

        # ---- Compute statistics ----
        result.net_pnl = equity - initial_capital
        result.gross_pnl = gross_wins - gross_losses
        result.total_fees = result.gross_pnl - result.net_pnl

        if result.total_trades > 0:
            result.win_rate = result.wins / result.total_trades
            if result.wins > 0:
                result.avg_win_r /= result.wins
            if result.losses > 0:
                result.avg_loss_r /= result.losses
            result.expectancy = (
                result.win_rate * result.avg_win_r - (1 - result.win_rate) * result.avg_loss_r
            )

        result.profit_factor = gross_wins / max(gross_losses, 1e-10)
        result.sharpe = self._sharpe(bar_returns)
        result.sortino = self._sortino(bar_returns)

        return result

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def _check_exit(self, pos: dict, bar: pd.Series, bar_idx: int) -> Tuple[Optional[float], str]:
        high = float(bar["h"])
        low = float(bar["l"])
        close = float(bar["c"])
        atr = pos["atr"]

        # ---- Stop loss ----
        if low <= pos["stop_loss"]:
            return pos["stop_loss"], "STOP"

        # ---- TP1 partial (simulate: fill at TP1 price within bar) ----
        if not pos["tp1_taken"] and high >= pos["tp1"]:
            pos["tp1_taken"] = True
            pos["qty"] *= 1 - self.cfg.atr_tp1_frac
            # Activate trailing stop after TP1
            pos["trail_active"] = True
            # Update stop to breakeven
            pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])

        # ---- TP2 partial ----
        if pos["tp1_taken"] and not pos["tp2_taken"] and high >= pos["tp2"]:
            pos["tp2_taken"] = True
            pos["qty"] *= 1 - self.cfg.atr_tp2_frac / (1 - self.cfg.atr_tp1_frac + 1e-9)

        # ---- Chandelier trailing stop ----
        if pos["trail_active"]:
            trail_stop = high - 2.0 * atr
            pos["stop_loss"] = max(pos["stop_loss"], trail_stop)
            if low <= pos["stop_loss"]:
                return pos["stop_loss"], "TRAIL_STOP"

        # ---- Time stop ----
        bars_held = bar_idx - pos["entry_bar"]
        if bars_held >= self.cfg.time_stop_candles:
            unrealised = (close - pos["entry_price"]) * pos["qty"]
            if unrealised <= 0:
                return close * (1 - self.SLIPPAGE), "TIME_STOP"

        return None, ""

    # ------------------------------------------------------------------

    def _close_position(
        self, pos: dict, price: float, reason: str, equity: float
    ) -> Tuple[float, float]:
        # Stop/TP prices are already limit prices hit within the bar - no extra slippage
        if reason in ("STOP", "TRAIL_STOP", "TP1", "TP2"):
            fill_price = price
        else:
            fill_price = price * (1 - self.SLIPPAGE)
        gross = (fill_price - pos["entry_price"]) * pos["qty"]
        fee = fill_price * pos["qty"] * self.TAKER_FEE
        net = gross - fee - pos["entry_fee"]
        equity += net
        return equity, net

    # ------------------------------------------------------------------
    # Performance metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _sharpe(returns: List[float], risk_free: float = 0.0) -> float:
        if len(returns) < 5:
            return 0.0
        arr = np.array(returns)
        std = arr.std()
        if std == 0:
            return 0.0
        return float((arr.mean() - risk_free) / std * np.sqrt(252))

    @staticmethod
    def _sortino(returns: List[float], risk_free: float = 0.0) -> float:
        if len(returns) < 5:
            return 0.0
        arr = np.array(returns)
        downside = arr[arr < 0]
        if len(downside) == 0:
            return float("inf")
        dd_std = downside.std()
        if dd_std == 0:
            return 0.0
        return float((arr.mean() - risk_free) / dd_std * np.sqrt(252))


# ---------------------------------------------------------------------------
# Multi-symbol batch backtest runner
# ---------------------------------------------------------------------------


def run_batch_backtest(
    cfg: AegisConfig,
    ohlcv_data: Dict[str, pd.DataFrame],  # {symbol: df_15m}
    ml_model: Optional[XGBSignalModel] = None,
    signal_fusion: Optional[SignalFusion] = None,
    initial_capital: float = 10_000.0,
) -> Dict[str, BacktestResult]:
    """
    Run backtest for every symbol in ohlcv_data.
    Returns {symbol: BacktestResult}.
    """
    from typing import Dict as D

    backtester = Backtester(cfg, ml_model, signal_fusion)
    results: D[str, BacktestResult] = {}

    for symbol, df in ohlcv_data.items():
        if df is None or len(df) < 250:
            log.warning(f"Skipping {symbol}: insufficient data.")
            continue
        log.info(f"Running backtest: {symbol} ({len(df)} bars)...")
        result = backtester.run(df, symbol, initial_capital)
        results[symbol] = result
        log.info(result.summary())

    # Aggregate stats
    if results:
        all_pnl = sum(r.net_pnl for r in results.values())
        all_trades = sum(r.total_trades for r in results.values())
        log.info(
            f"=== BATCH SUMMARY: {len(results)} symbols, "
            f"{all_trades} trades, net PnL=${all_pnl:+.2f} ==="
        )

    return results
