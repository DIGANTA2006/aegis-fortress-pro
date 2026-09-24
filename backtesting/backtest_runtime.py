import asyncio
from dataclasses import dataclass
from datetime import datetime

from backtesting.equity_curve import EquityCurveTracker
from backtesting.fee_model import PercentageFeeModel
from backtesting.performance_metrics import PerformanceMetrics
from backtesting.replay_clock import ReplayClock
from backtesting.replay_market_data_service import ReplayMarketDataService
from backtesting.replay_source import ReplaySource
from backtesting.simulated_exchange import SimulatedExchange
from backtesting.slippage_model import BasisPointSlippageModel
from backtesting.strategy_replay_service import StrategyReplayService
from core.database_manager import DatabaseManager
from core.event_bus import EventBus
from core.exchange_registry import ExchangeRegistry
from core.smart_order_router import SmartOrderRouter
from core.state.portfolio_state_store import PortfolioStateStore
from core.task_supervisor import TaskSupervisor
from execution.execution_pipeline import ExecutionPipeline
from execution.fill_processor import FillProcessor
from feeds.market_data_normalizer import MarketDataNormalizer
from feeds.market_state_store import MarketStateStore
from microservices.execution_service import ExecutionService
from microservices.orchestrator import Orchestrator
from microservices.risk_event_logger_service import RiskEventLoggerService
from microservices.risk_service import RiskService
from portfolio.exposure_engine import ExposureEngine
from portfolio.position_ledger import PositionLedger
from risk.kill_switch import KillSwitch
from risk.portfolio_guard import PortfolioGuard
from risk.pre_trade_risk import PreTradeRiskValidator


@dataclass
class BacktestResult:
    performance: dict
    equity_curve: list[dict]
    trades: list[dict]
    risk_events: list[dict]
    replay_health: dict
    strategy_health: dict
    execution_health: dict
    risk_health: dict

    def to_dict(self) -> dict:
        return {
            "performance": self.performance,
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "risk_events": self.risk_events,
            "replay_health": self.replay_health,
            "strategy_health": self.strategy_health,
            "execution_health": self.execution_health,
            "risk_health": self.risk_health,
        }


class BacktestRuntime:
    def __init__(
        self,
        strategy,
        replay_file: str,
        initial_equity: float = 10000.0,
        replay_speed: float = 0.0,
        fee_rate: float = 0.0004,
        slippage_bps: float = 2.0,
        max_gross_exposure: float = 3000.0,
        max_net_exposure: float = 3000.0,
        max_symbol_weight: float = 1.0,
        max_order_notional: float = 1000.0,
        max_daily_loss: float = 500.0,
        max_drawdown_pct: float = 20.0,
    ) -> None:
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")

        self.strategy = strategy
        self.replay_file = replay_file
        self.initial_equity = initial_equity

        self.event_bus = EventBus()
        self.task_supervisor = TaskSupervisor()

        self.database = DatabaseManager(
            db_path="data/aegis_backtest.db",
        )

        self.replay_source = ReplaySource(
            replay_file
        )

        self.replay_clock = ReplayClock(
            speed=replay_speed,
        )

        self.market_normalizer = MarketDataNormalizer()

        self.market_state_store = MarketStateStore(
            stale_after_seconds=10_000_000.0,
        )

        self.simulated_exchange = SimulatedExchange(
            fee_model=PercentageFeeModel(
                rate=fee_rate,
            ),
            slippage_model=BasisPointSlippageModel(
                bps=slippage_bps,
            ),
        )

        self.exchange_registry = ExchangeRegistry()
        self.exchange_registry.register(
            "SIMULATED",
            self.simulated_exchange,
        )

        self.router = SmartOrderRouter(
            self.exchange_registry
        )

        self.ledger = PositionLedger()
        self.exposure_engine = ExposureEngine()

        self.portfolio_guard = PortfolioGuard(
            max_gross_exposure=max_gross_exposure,
            max_net_exposure=max_net_exposure,
            max_symbol_weight=max_symbol_weight,
        )

        self.state_store = PortfolioStateStore(
            path="data/backtest_portfolio_state.json",
        )

        self.fill_processor = FillProcessor(
            ledger=self.ledger,
            exposure_engine=self.exposure_engine,
            portfolio_guard=self.portfolio_guard,
            state_store=self.state_store,
            database=self.database,
        )

        self.pre_trade_risk = PreTradeRiskValidator(
            exposure_engine=self.exposure_engine,
            portfolio_guard=self.portfolio_guard,
            max_order_notional=max_order_notional,
        )

        self.execution_pipeline = ExecutionPipeline(
            router=self.router,
            ledger=self.ledger,
            pre_trade_risk=self.pre_trade_risk,
            fill_processor=self.fill_processor,
            event_bus=self.event_bus,
            database=self.database,
        )

        self.kill_switch = KillSwitch(
            max_daily_loss=max_daily_loss,
            max_drawdown_pct=max_drawdown_pct,
        )

        self.replay_service = ReplayMarketDataService(
            event_bus=self.event_bus,
            replay_source=self.replay_source,
            replay_clock=self.replay_clock,
            normalizer=self.market_normalizer,
            market_state_store=self.market_state_store,
            simulated_exchange=self.simulated_exchange,
        )

        self.strategy_service = StrategyReplayService(
            event_bus=self.event_bus,
            strategy=self.strategy,
            market_state_store=self.market_state_store,
        )

        self.execution_service = ExecutionService(
            event_bus=self.event_bus,
            execution_pipeline=self.execution_pipeline,
        )

        self.risk_service = RiskService(
            event_bus=self.event_bus,
            kill_switch=self.kill_switch,
        )

        self.risk_event_logger = RiskEventLoggerService(
            event_bus=self.event_bus,
            log_file="logs/backtest_risk_events.jsonl",
            database=self.database,
        )

        self.orchestrator = Orchestrator(
            event_bus=self.event_bus,
            task_supervisor=self.task_supervisor,
            services=[
                self.replay_service,
                self.strategy_service,
                self.execution_service,
                self.risk_service,
                self.risk_event_logger,
            ],
        )

        self.equity_curve = EquityCurveTracker(
            initial_equity=initial_equity,
        )

    async def run(self) -> BacktestResult:
        await self.orchestrator.start()

        while self.replay_service.running:
            self._record_equity_point()
            await asyncio.sleep(0)

        await asyncio.sleep(0.1)

        self._record_equity_point()

        await self.orchestrator.stop()

        trades = [
            trade.to_dict()
            for trade in self.ledger.trades()
        ]

        trade_pnls = [
            trade.pnl
            for trade in self.ledger.trades()
        ]

        equity_values = self.equity_curve.values()

        performance = PerformanceMetrics().calculate(
            equity_values=equity_values,
            trade_pnls=trade_pnls,
        )

        risk_events = self.database.fetch_recent_risk_events(
            limit=100000,
        )

        return BacktestResult(
            performance=performance,
            equity_curve=self.equity_curve.to_dict(),
            trades=trades,
            risk_events=risk_events,
            replay_health=self.replay_service.health(),
            strategy_health=self.strategy_service.health(),
            execution_health=self.execution_service.health(),
            risk_health=self.risk_service.health(),
        )

    def run_sync(self) -> BacktestResult:
        return asyncio.run(
            self.run()
        )

    def _record_equity_point(self) -> None:
        mark_prices = self.market_state_store.mark_prices()

        self.ledger.mark_positions(
            mark_prices
        )

        positions = self.ledger.positions()

        exposure = self.exposure_engine.calculate(
            positions=positions,
            mark_prices=mark_prices,
        )

        realized_pnl = self.ledger.realized_pnl()

        unrealized_pnl = sum(
            position.unrealized_pnl
            for position in positions.values()
        )

        timestamp = (
            self.replay_clock.current_time
            or datetime.utcnow()
        )

        self.equity_curve.record(
            timestamp=timestamp,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            gross_exposure=exposure.gross_exposure,
            net_exposure=exposure.net_exposure,
        )
