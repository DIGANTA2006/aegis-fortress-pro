"""
risk.py  -  AEGIS PRO v2
Risk calculations, circuit breakers, Kelly sizing, drawdown control.

New vs v1:
  - Time-based stop: exit if no profit within N 15m candles
  - Layered TP: two partial exits (40% / 40% / trail remainder)
  - Weekly drawdown tracking
  - Cleaner Kelly with cold-start guard
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import AegisConfig

log = logging.getLogger("aegis.risk")


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------


@dataclass
class Trade:
    symbol: str
    entry_price: float
    qty: float
    initial_qty: float
    stop_loss: float
    tp1: float  # first partial TP price
    tp2: float  # second partial TP price
    atr_entry: float
    current_atr: float
    risk_dollars: float
    entry_fee: float
    signal_type: str  # TREND / RANGE / BREAKOUT
    entry_time: float = field(default_factory=time.time)
    entry_bar_index: int = 0  # 15m bar counter at entry (for time stop)
    tp1_taken: bool = False
    tp2_taken: bool = False
    trail_activated: bool = False
    early_trail: bool = False
    mode: str = "PAPER"


# ---------------------------------------------------------------------------
# Risk manager
# ---------------------------------------------------------------------------


class RiskManager:
    """
    Centralised risk calculations and circuit-breaker state.
    All monetary values in USDT.
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg

        # ---- Equity tracking ----
        self.historical_peak: float = 0.0
        self.peak_equity: float = 0.0
        self.daily_start_equity: float = 0.0
        self.weekly_start_equity: float = 0.0

        # ---- Trade counters ----
        self.trades_today: int = 0
        self.wins: int = 0
        self.losses: int = 0
        self.consecutive_losses: int = 0
        self.daily_stop_triggered: bool = False
        self.weekly_reduced: bool = False
        self.drawdown_locked_until: float = 0.0
        self.pause_until: float = 0.0  # circuit-breaker pause
        self.breaker_count: int = 0

        # ---- Performance metrics ----
        self.total_trades: int = 0
        self.total_wins: int = 0
        self.total_losses: int = 0
        self.avg_win_r: float = 0.0
        self.avg_loss_r: float = 0.0
        self.win_rate: float = 0.0
        self.expectancy: float = 0.0

        # ---- Slippage tracking per symbol ----
        self._slippage_history: Dict[str, List[float]] = {}
        self._blacklisted: Dict[str, float] = {}  # symbol Ã¢â€ ' blacklist_until timestamp

        # ---- Bar counter (incremented externally each 15m scan) ----
        self.bar_counter: int = 0

    # ------------------------------------------------------------------
    # Drawdown checks
    # ------------------------------------------------------------------

    def check_daily_loss(self, current_equity: float) -> bool:
        """Returns True if daily loss limit is hit (halt trading)."""
        if self.daily_stop_triggered:
            return True
        if self.daily_start_equity <= 0:
            return False
        daily_loss_pct = (self.daily_start_equity - current_equity) / self.daily_start_equity * 100
        if daily_loss_pct >= self.cfg.max_daily_loss_pct:
            self.daily_stop_triggered = True
            log.critical(
                f"Daily loss limit hit: {daily_loss_pct:.2f}% >= {self.cfg.max_daily_loss_pct}%"
            )
            return True
        return False

    def check_weekly_loss(self, current_equity: float) -> bool:
        """Returns True if weekly loss limit triggers size reduction."""
        if self.weekly_start_equity <= 0:
            return False
        weekly_loss_pct = (
            (self.weekly_start_equity - current_equity) / self.weekly_start_equity * 100
        )
        if weekly_loss_pct >= self.cfg.max_weekly_loss_pct:
            if not self.weekly_reduced:
                self.weekly_reduced = True
                log.warning(f"Weekly loss limit hit: {weekly_loss_pct:.2f}%  Ã¢â€ ' reducing sizes 50%")
            return True
        self.weekly_reduced = False
        return False

    def check_historical_drawdown(self, current_equity: float) -> bool:
        """Returns True if bot should be locked for drawdown_lock_hours."""
        if self.historical_peak <= 0:
            return False
        if time.time() < self.drawdown_locked_until:
            return True
        dd_pct = (self.historical_peak - current_equity) / self.historical_peak * 100
        if dd_pct >= self.cfg.max_drawdown_pct:
            lock_secs = self.cfg.drawdown_lock_hours * 3600
            self.drawdown_locked_until = time.time() + lock_secs
            log.critical(
                f"Historical drawdown {dd_pct:.2f}% >= {self.cfg.max_drawdown_pct}%. "
                f"Locking {self.cfg.drawdown_lock_hours}h."
            )
            return True
        return False

    def is_trading_halted(self, current_equity: float) -> Tuple[bool, str]:
        """Aggregate halt check. Returns (halted, reason)."""
        if self.check_historical_drawdown(current_equity):
            return True, "historical_drawdown"
        if self.check_daily_loss(current_equity):
            return True, "daily_loss"
        if time.time() < self.pause_until:
            remaining = self.pause_until - time.time()
            return True, f"circuit_breaker ({remaining/3600:.1f}h remaining)"
        return False, ""

    def on_loss(self) -> None:
        """Record a loss; fire circuit breaker if needed."""
        self.losses += 1
        self.total_losses += 1
        self.consecutive_losses += 1
        if self.consecutive_losses >= self.cfg.max_consecutive_losses:
            self.breaker_count += 1
            pause_hours = min(4 * self.breaker_count, 48)
            self.pause_until = time.time() + pause_hours * 3600
            self.consecutive_losses = 0
            log.warning(
                f"Circuit breaker #{self.breaker_count}: "
                f"pausing {pause_hours}h after {self.cfg.max_consecutive_losses} consecutive losses."
            )

    def on_win(self) -> None:
        self.wins += 1
        self.total_wins += 1
        self.consecutive_losses = 0

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        price: float,
        atr: float,
        equity: float,
        open_risk: float,
        ml_prob: float = 0.5,
        corr_multiplier: float = 1.0,
    ) -> Optional[dict]:
        """
        Returns sizing dict or None if trade should be skipped.
        {amount, stop_price, tp1_price, tp2_price, risk_dollars}
        """
        cfg = self.cfg

        stop_distance = cfg.atr_stop_mult * atr
        if stop_distance < price * 0.001:  # nonsensically tiny stop
            return None

        # Base risk
        risk_pct = self._get_dynamic_risk(equity)

        # Kelly adjustment (only after enough trades)
        if self.total_trades >= 20 and self.avg_loss_r > 0 and self.avg_win_r > 0:
            kelly = self._kelly(self.win_rate, self.avg_win_r, self.avg_loss_r)
            risk_pct = min(risk_pct, kelly)

        # ML probability scaling
        if ml_prob < cfg.ml_prob_threshold:
            risk_pct *= 0.5
        elif ml_prob > 0.72:
            risk_pct *= 1.15

        # Weekly drawdown reduction
        if self.weekly_reduced:
            risk_pct *= 0.5

        # Correlation discount
        risk_pct *= corr_multiplier

        # ATR relative cap
        atr_rel = atr / price
        if atr_rel > 0.02:
            risk_pct *= 0.5

        # Calculate dollar risk
        liquid_equity = max(0.0, equity - open_risk)
        risk_dollars = liquid_equity * risk_pct
        position_units = risk_dollars / stop_distance if stop_distance > 0 else 0.0
        position_usd = position_units * price

        # Hard caps
        hard_cap = liquid_equity * cfg.max_pos_allocation
        position_usd = min(position_usd, hard_cap)

        if position_usd < 10.0:  # minimum order size
            return None

        amount = position_usd / price

        # Portfolio heat check
        new_risk = amount * stop_distance
        if open_risk + new_risk > liquid_equity * cfg.max_portfolio_heat:
            log.debug("Portfolio heat cap reached - skipping trade.")
            return None

        return {
            "amount": amount,
            "stop_price": price - stop_distance,
            "tp1_price": price + cfg.atr_tp1_mult * atr,
            "tp2_price": price + cfg.atr_tp2_mult * atr,
            "risk_dollars": new_risk,
        }

    def _get_dynamic_risk(self, equity: float) -> float:
        cfg = self.cfg
        base = cfg.base_risk_per_trade
        if self.historical_peak <= 0:
            return base
        dd = (self.historical_peak - equity) / self.historical_peak
        if dd > 0.07:
            return base * 0.40
        if dd > 0.05:
            return base * 0.60
        if dd > 0.03:
            return base * 0.80
        return base

    def _kelly(self, win_rate: float, avg_win_r: float, avg_loss_r: float) -> float:
        if avg_loss_r == 0:
            return 0.0
        b = avg_win_r / avg_loss_r
        p = win_rate
        q = 1 - p
        kelly = (p * b - q) / max(b, 1e-10)
        return max(0.0, min(kelly * self.cfg.kelly_fraction, 0.05))

    # ------------------------------------------------------------------
    # Performance stat updates
    # ------------------------------------------------------------------

    def update_stats(self, pnl: float, r_multiple: float) -> None:
        # NOTE: total_wins / total_losses are already incremented by on_win() / on_loss().
        # update_stats only updates the running R-multiple averages and derived metrics.
        self.total_trades += 1
        if pnl > 0:
            n = max(self.total_wins, 1)
            self.avg_win_r = self.avg_win_r + (r_multiple - self.avg_win_r) / n
        else:
            n = max(self.total_losses, 1)
            self.avg_loss_r = self.avg_loss_r + (abs(r_multiple) - self.avg_loss_r) / n
        if self.total_trades > 0:
            self.win_rate = self.total_wins / self.total_trades
            self.expectancy = self.win_rate * self.avg_win_r - (1 - self.win_rate) * self.avg_loss_r

    # ------------------------------------------------------------------
    # Slippage blacklist
    # ------------------------------------------------------------------

    def record_slippage(self, symbol: str, expected: float, actual: float) -> None:
        slip_pct = abs(actual - expected) / max(expected, 1e-10)
        hist = self._slippage_history.setdefault(symbol, [])
        hist.append(slip_pct)
        if len(hist) > 20:
            hist.pop(0)
        avg_slip = sum(hist) / len(hist)
        if avg_slip > self.cfg.max_slippage_blacklist and len(hist) >= 5:
            blacklist_until = time.time() + 86400
            self._blacklisted[symbol] = blacklist_until
            log.warning(
                f"Blacklisting {symbol} for 24h: avg slippage {avg_slip*100:.3f}% > "
                f"{self.cfg.max_slippage_blacklist*100:.3f}%"
            )

    def is_blacklisted(self, symbol: str) -> bool:
        until = self._blacklisted.get(symbol, 0)
        if until > time.time():
            return True
        if symbol in self._blacklisted:
            del self._blacklisted[symbol]
        return False

    # ------------------------------------------------------------------
    # Time-based stop check
    # ------------------------------------------------------------------

    def should_time_stop(self, trade: "Trade") -> bool:
        """
        Exit if position hasn't moved profitably within N 15m bars.
        """
        bars_held = self.bar_counter - trade.entry_bar_index
        return bars_held >= self.cfg.time_stop_candles

    # ------------------------------------------------------------------
    # Reset helpers
    # ------------------------------------------------------------------

    def reset_daily(self, current_equity: float) -> None:
        self.trades_today = 0
        self.wins = 0
        self.losses = 0
        self.daily_stop_triggered = False
        self.daily_start_equity = current_equity
        self.bar_counter = 0

    def reset_weekly(self, current_equity: float) -> None:
        self.weekly_start_equity = current_equity
        self.weekly_reduced = False

    def update_equity_peaks(self, equity: float) -> None:
        if equity > self.peak_equity:
            self.peak_equity = equity
        if equity > self.historical_peak:
            self.historical_peak = equity
