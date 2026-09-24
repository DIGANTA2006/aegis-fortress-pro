"""
Boot smoke test – imports every top-level package to catch circular
imports and missing dependencies early.
"""
import importlib
import pytest

MODULES = [
    "models.order",
    "models.trade",
    "execution.execution_validator",
    "execution.order_state_machine",
    "core.events.base_event",
    "core.events.market_event",
    "core.events.order_event",
    "ai.liquidity_scorer",
    "ai.regime_detector",
    "ai.strategy_selector",
    "backtesting.backtest_engine",
    "backtesting.equity_curve",
    "backtesting.performance_metrics",
    "backtesting.walk_forward",
    "strategies.base_strategy",
    "strategies.smart_spread",
    "strategies.arbitrage_detector",
    "portfolio.capital_allocator",
    "portfolio.correlation_engine",
    "portfolio.portfolio_risk",
    "portfolio.strategy_weights",
    "risk.adaptive_position_sizing",
    "monitoring.health_checks",
    "metrics.metrics_registry",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_importable(module):
    mod = importlib.import_module(module)
    assert mod is not None
