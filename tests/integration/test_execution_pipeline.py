import asyncio

from backtesting.fee_model import PercentageFeeModel
from backtesting.simulated_exchange import SimulatedExchange
from backtesting.slippage_model import BasisPointSlippageModel
from core.exchange_registry import ExchangeRegistry
from core.smart_order_router import SmartOrderRouter
from core.state.portfolio_state_store import PortfolioStateStore
from execution.execution_pipeline import ExecutionPipeline
from execution.fill_processor import FillProcessor
from models.market_tick import MarketTick
from models.order import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from portfolio.exposure_engine import ExposureEngine
from portfolio.position_ledger import PositionLedger
from risk.portfolio_guard import PortfolioGuard
from risk.pre_trade_risk import PreTradeRiskValidator


def test_execution_pipeline_market_buy_fill(tmp_path):
    exchange = SimulatedExchange(
        fee_model=PercentageFeeModel(rate=0.0),
        slippage_model=BasisPointSlippageModel(bps=0.0),
    )

    exchange.update_tick(
        MarketTick(
            symbol="BTC/USDT",
            exchange="SIMULATED",
            bid=100.0,
            ask=101.0,
            last=100.5,
            volume=10.0,
        )
    )

    registry = ExchangeRegistry()
    registry.register(
        "SIMULATED",
        exchange,
    )

    router = SmartOrderRouter(
        registry
    )

    ledger = PositionLedger()
    exposure_engine = ExposureEngine()

    portfolio_guard = PortfolioGuard(
        max_gross_exposure=100000.0,
        max_net_exposure=100000.0,
        max_symbol_weight=1.0,
    )

    fill_processor = FillProcessor(
        ledger=ledger,
        exposure_engine=exposure_engine,
        portfolio_guard=portfolio_guard,
        state_store=PortfolioStateStore(
            path=str(tmp_path / "portfolio_state.json")
        ),
    )

    risk_validator = PreTradeRiskValidator(
        exposure_engine=exposure_engine,
        portfolio_guard=portfolio_guard,
        max_order_notional=100000.0,
    )

    pipeline = ExecutionPipeline(
        router=router,
        ledger=ledger,
        pre_trade_risk=risk_validator,
        fill_processor=fill_processor,
    )

    order = Order(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
    )

    result = asyncio.run(
        pipeline.submit(
            order=order,
            mark_prices={
                "BTC/USDT": 100.5,
            },
        )
    )

    assert result.accepted is True
    assert result.execution_report is not None
    assert result.execution_report.status == OrderStatus.FILLED

    position = ledger.get_position("BTC/USDT")

    assert position is not None
    assert position.quantity == 1.0
    assert position.average_entry == 101.0
