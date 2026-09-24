from dataclasses import dataclass, field

from core.state.portfolio_state_store import PortfolioStateStore
from models.execution_report import ExecutionReport
from portfolio.exposure_engine import ExposureEngine, ExposureSnapshot
from portfolio.position_ledger import PositionLedger
from risk.portfolio_guard import PortfolioGuard, RiskBreach


@dataclass
class FillProcessingResult:
    processed: bool
    trade: object | None = None
    exposure_snapshot: ExposureSnapshot | None = None
    breaches: list[RiskBreach] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "processed": self.processed,
            "trade": self.trade.to_dict() if self.trade else None,
            "exposure_snapshot": (
                self.exposure_snapshot.to_dict()
                if self.exposure_snapshot
                else None
            ),
            "breaches": [breach.to_dict() for breach in self.breaches],
        }


class FillProcessor:
    def __init__(
        self,
        ledger: PositionLedger,
        exposure_engine: ExposureEngine,
        portfolio_guard: PortfolioGuard,
        state_store: PortfolioStateStore,
        database=None,
    ) -> None:
        self.ledger = ledger
        self.exposure_engine = exposure_engine
        self.portfolio_guard = portfolio_guard
        self.state_store = state_store
        self.database = database

    def process(
        self,
        report: ExecutionReport,
        mark_prices: dict[str, float] | None = None,
        strategy_id: str | None = None,
    ) -> FillProcessingResult:
        mark_prices = mark_prices or {}

        if not report.has_fill():
            return FillProcessingResult(processed=False)

        fill_price = report.average_fill_price

        if fill_price <= 0:
            raise ValueError("Execution report has fill quantity but no valid fill price")

        trade = self.ledger.apply_fill(
            symbol=report.symbol,
            side=report.side,
            quantity=report.filled_quantity,
            price=fill_price,
            exchange=report.exchange,
            fee=report.fee,
            strategy_id=strategy_id,
            order_id=report.exchange_order_id,
        )

        if self.database is not None:
            self.database.record_trade(
                trade
            )

        self.ledger.mark_positions(mark_prices)

        positions = self.ledger.positions()

        exposure_snapshot = self.exposure_engine.calculate(
            positions=positions,
            mark_prices=mark_prices,
        )

        breaches = self.portfolio_guard.validate(
            exposure_snapshot
        )

        state_payload = {
            "portfolio": self.ledger.snapshot(),
            "exposure": exposure_snapshot.to_dict(),
            "breaches": [breach.to_dict() for breach in breaches],
            "last_execution_report": report.to_dict(),
        }

        self.state_store.save(state_payload)

        return FillProcessingResult(
            processed=True,
            trade=trade,
            exposure_snapshot=exposure_snapshot,
            breaches=breaches,
        )
