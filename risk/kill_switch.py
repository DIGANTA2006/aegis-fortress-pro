import logging
from datetime import datetime


log = logging.getLogger(__name__)


class KillSwitch:
    def __init__(
        self,
        max_daily_loss: float,
        max_drawdown_pct: float,
    ) -> None:
        if max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")

        if max_drawdown_pct <= 0:
            raise ValueError("max_drawdown_pct must be positive")

        self.max_daily_loss = max_daily_loss
        self.max_drawdown_pct = max_drawdown_pct

        self.daily_pnl = 0.0
        self.peak_balance: float | None = None

        self.triggered = False
        self.reason: str | None = None
        self.triggered_at: datetime | None = None

    def trigger(self, reason: str) -> None:
        if self.triggered:
            return

        self.triggered = True
        self.reason = reason
        self.triggered_at = datetime.utcnow()

        log.critical("Kill switch triggered: %s", reason)

    def reset(self) -> None:
        self.triggered = False
        self.reason = None
        self.triggered_at = None
        self.daily_pnl = 0.0
        self.peak_balance = None

        log.warning("Kill switch reset")

    def update_balance(self, current_balance: float) -> bool:
        if current_balance <= 0:
            self.trigger("Current balance is zero or negative")
            return False

        if self.peak_balance is None:
            self.peak_balance = current_balance

        if current_balance > self.peak_balance:
            self.peak_balance = current_balance

        drawdown_pct = (
            (self.peak_balance - current_balance)
            / self.peak_balance
        ) * 100

        if drawdown_pct >= self.max_drawdown_pct:
            self.trigger(
                f"Drawdown {drawdown_pct:.4f}% exceeded "
                f"limit {self.max_drawdown_pct:.4f}%"
            )
            return False

        return not self.triggered

    def update_pnl(self, pnl: float) -> bool:
        self.daily_pnl += pnl

        if self.daily_pnl <= -abs(self.max_daily_loss):
            self.trigger(
                f"Daily loss {self.daily_pnl:.8f} exceeded "
                f"limit {-abs(self.max_daily_loss):.8f}"
            )
            return False

        return not self.triggered

    def is_active(self) -> bool:
        return not self.triggered

    def status(self) -> dict:
        return {
            "active": self.is_active(),
            "triggered": self.triggered,
            "reason": self.reason,
            "triggered_at": (
                self.triggered_at.isoformat()
                if self.triggered_at
                else None
            ),
            "daily_pnl": self.daily_pnl,
            "peak_balance": self.peak_balance,
        }
