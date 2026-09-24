import os
from dataclasses import dataclass

from app.runtime_settings import RuntimeSettings
from config import load_config, validate_config
from core.database_manager import DatabaseManager
from core.event_bus import EventBus
from core.exchange_registry import ExchangeRegistry
from core.smart_order_router import SmartOrderRouter
from core.state.portfolio_state_store import PortfolioStateStore
from core.task_supervisor import TaskSupervisor
from exchange import ExchangeManager
from execution.execution_pipeline import ExecutionPipeline
from execution.fill_processor import FillProcessor
from feeds.exchange_polling_source import ExchangePollingSource
from feeds.market_data_normalizer import MarketDataNormalizer
from feeds.market_state_store import MarketStateStore
from microservices.execution_service import ExecutionService
from microservices.health_server_service import HealthServerService
from microservices.live_strategy_service import LiveStrategyService
from microservices.market_data_service import MarketDataService
from microservices.momentum_trap_service import MomentumTrapService
from microservices.monitoring_service import MonitoringService
from microservices.orchestrator import Orchestrator
from microservices.risk_event_logger_service import RiskEventLoggerService
from microservices.risk_service import RiskService
from monitoring.health_server import HealthServer
from monitoring.runtime_health import RuntimeHealthAggregator
from monitoring.runtime_metrics import RuntimeMetrics
from portfolio.exposure_engine import ExposureEngine
from portfolio.position_ledger import PositionLedger
from portfolio.symbol_discovery import discover_tradeable_symbols
from risk.kill_switch import KillSwitch
from risk.portfolio_guard import PortfolioGuard
from risk.pre_trade_risk import PreTradeRiskValidator
from strategies.mean_reversion_imbalance import MeanReversionImbalanceStrategy


@dataclass
class RuntimeContainer:
    config: object
    settings: RuntimeSettings

    database: DatabaseManager
    event_bus: EventBus
    task_supervisor: TaskSupervisor

    exchange_manager: ExchangeManager
    exchange_registry: ExchangeRegistry
    router: SmartOrderRouter

    market_source: ExchangePollingSource
    market_normalizer: MarketDataNormalizer
    market_state_store: MarketStateStore
    market_data_service: MarketDataService

    ledger: PositionLedger
    exposure_engine: ExposureEngine
    portfolio_guard: PortfolioGuard
    state_store: PortfolioStateStore
    fill_processor: FillProcessor
    pre_trade_risk: PreTradeRiskValidator
    execution_pipeline: ExecutionPipeline
    kill_switch: KillSwitch

    live_strategy: MeanReversionImbalanceStrategy | None
    live_strategy_service: LiveStrategyService | None
    momentum_trap_service: MomentumTrapService

    execution_service: ExecutionService
    risk_service: RiskService
    risk_event_logger_service: RiskEventLoggerService

    runtime_metrics: RuntimeMetrics
    monitoring_service: MonitoringService

    health_aggregator: RuntimeHealthAggregator
    health_server: HealthServer
    health_server_service: HealthServerService

    orchestrator: Orchestrator

    @classmethod
    def build(cls) -> "RuntimeContainer":
        cfg = load_config()

        config_errors = validate_config(cfg)

        if config_errors:
            raise RuntimeError(
                "Configuration validation failed: "
                + " | ".join(config_errors)
            )

        settings = RuntimeSettings.from_config(cfg)
        settings.validate()

        database = DatabaseManager(
            db_path=settings.database_path,
        )

        event_bus = EventBus()
        task_supervisor = TaskSupervisor()

        exchange_manager = ExchangeManager(cfg)

        runtime_symbols = settings.market_symbols
        symbols_provider = None

        if settings.auto_symbol_discovery_enabled:
            def symbols_provider() -> tuple[str, ...]:
                return discover_tradeable_symbols(
                    exchange_manager,
                    quote=settings.symbol_discovery_quote,
                    max_symbols=settings.symbol_discovery_max_symbols,
                    min_quote_volume=settings.symbol_discovery_min_quote_volume,
                    min_change_pct=settings.symbol_discovery_min_change_pct,
                    max_change_pct=settings.symbol_discovery_max_change_pct,
                    max_spread_bps=settings.symbol_discovery_max_spread_bps,
                    excluded_symbols=settings.symbol_discovery_excluded_symbols,
                    fallback_symbols=settings.market_symbols,
                )

            runtime_symbols = symbols_provider()
            settings.market_symbols = runtime_symbols

        if not runtime_symbols:
            raise RuntimeError(
                "No market symbols configured. Set AEGIS_MARKET_SYMBOLS "
                "or enable AEGIS_AUTO_SYMBOL_DISCOVERY."
            )

        exchange_registry = ExchangeRegistry()

        for name, exchange in exchange_manager.exchanges.items():
            exchange_registry.register(
                name,
                exchange,
            )

        router = SmartOrderRouter(
            exchange_registry
        )

        market_source = ExchangePollingSource(
            exchange_registry=exchange_registry,
            symbols=runtime_symbols,
            poll_interval_seconds=settings.market_poll_interval_seconds,
            orderbook_depth=settings.orderbook_depth,
            symbols_provider=symbols_provider,
            max_concurrent_fetches=settings.market_fetch_concurrency,
            symbol_refresh_interval_seconds=(
                settings.symbol_discovery_refresh_seconds
            ),
        )

        market_normalizer = MarketDataNormalizer()

        market_state_store = MarketStateStore(
            stale_after_seconds=settings.market_stale_after_seconds,
        )

        market_data_service = MarketDataService(
            event_bus=event_bus,
            market_source=market_source,
            normalizer=market_normalizer,
            market_state_store=market_state_store,
        )

        ledger = PositionLedger()
        exposure_engine = ExposureEngine()

        portfolio_guard = PortfolioGuard(
            max_gross_exposure=settings.max_gross_exposure,
            max_net_exposure=settings.max_net_exposure,
            max_symbol_weight=settings.max_symbol_weight,
        )

        state_store = PortfolioStateStore(
            path=os.environ.get(
                "AEGIS_PORTFOLIO_STATE_PATH",
                "data/portfolio_state.json",
            )
        )

        saved_portfolio_state = state_store.load().get(
            "portfolio",
            {},
        )

        if hasattr(ledger, "restore_snapshot"):
            ledger.restore_snapshot(
                saved_portfolio_state
            )

        fill_processor = FillProcessor(
            ledger=ledger,
            exposure_engine=exposure_engine,
            portfolio_guard=portfolio_guard,
            state_store=state_store,
            database=database,
        )

        pre_trade_risk = PreTradeRiskValidator(
            exposure_engine=exposure_engine,
            portfolio_guard=portfolio_guard,
            max_order_notional=settings.max_order_notional,
            min_order_notional=settings.strategy_min_order_notional,
        )

        execution_pipeline = ExecutionPipeline(
            router=router,
            ledger=ledger,
            pre_trade_risk=pre_trade_risk,
            fill_processor=fill_processor,
            event_bus=event_bus,
            database=database,
        )

        kill_switch = KillSwitch(
            max_daily_loss=settings.max_daily_loss,
            max_drawdown_pct=settings.max_drawdown_pct,
        )

        live_strategy = None
        live_strategy_service = None

        if settings.live_strategy_enabled:
            live_strategy = MeanReversionImbalanceStrategy(
                ledger=ledger,
                kill_switch=kill_switch,
                target_notional=settings.strategy_target_notional,
                max_position_notional=settings.strategy_max_position_notional,
                rolling_window=settings.strategy_rolling_window,
                min_observations=settings.strategy_min_observations,
                entry_zscore=settings.strategy_entry_zscore,
                exit_zscore=settings.strategy_exit_zscore,
                imbalance_threshold=settings.strategy_imbalance_threshold,
                max_spread_bps=settings.strategy_max_spread_bps,
                cooldown_seconds=settings.strategy_cooldown_seconds,
                order_type=settings.strategy_order_type,
                min_order_notional=settings.strategy_min_order_notional,
                take_profit_bps=settings.strategy_take_profit_bps,
                stop_loss_bps=settings.strategy_stop_loss_bps,
                min_profit_after_fee_bps=settings.strategy_min_profit_after_fee_bps,
                max_hold_seconds=settings.strategy_max_hold_seconds,
                cooldown_after_exit_seconds=(
                    settings.strategy_symbol_cooldown_after_exit_seconds
                ),
                loss_cooldown_seconds=settings.strategy_loss_cooldown_seconds,
                bad_symbol_drop_bps=settings.strategy_bad_symbol_drop_bps,
            )

            live_strategy_service = LiveStrategyService(
                event_bus=event_bus,
                strategy=live_strategy,
                market_state_store=market_state_store,
            )

        momentum_trap_service = MomentumTrapService(
            event_bus=event_bus,
            exchange_manager=exchange_manager,
            ledger=ledger,
            kill_switch=kill_switch,
            market_state_store=market_state_store,
            symbols=runtime_symbols,
            target_notional=settings.strategy_target_notional,
            max_position_notional=settings.strategy_max_position_notional,
            min_order_notional=settings.strategy_min_order_notional,
            order_type=settings.strategy_order_type,
        )

        execution_service = ExecutionService(
            event_bus=event_bus,
            execution_pipeline=execution_pipeline,
        )

        risk_service = RiskService(
            event_bus=event_bus,
            kill_switch=kill_switch,
        )

        risk_event_logger_service = RiskEventLoggerService(
            event_bus=event_bus,
            log_file="logs/risk_events.jsonl",
            database=database,
        )

        runtime_metrics = RuntimeMetrics(
            port=settings.metrics_port,
        )

        monitoring_service = MonitoringService(
            event_bus=event_bus,
            metrics=runtime_metrics,
            market_state_store=market_state_store,
            kill_switch=kill_switch,
            database=database,
            interval_seconds=settings.monitoring_interval_seconds,
        )

        orchestrator_ref = {
            "value": None
        }

        health_aggregator = RuntimeHealthAggregator(
            orchestrator_provider=lambda: orchestrator_ref["value"],
            market_state_store=market_state_store,
            kill_switch=kill_switch,
            database=database,
        )

        health_server = HealthServer(
            host=settings.health_host,
            port=settings.health_port,
            status_provider=health_aggregator.status,
        )

        health_server_service = HealthServerService(
            health_server=health_server,
            health_aggregator=health_aggregator,
            database=database,
            snapshot_interval_seconds=settings.health_snapshot_interval_seconds,
        )

        services = [
            market_data_service,
        ]

        if live_strategy_service is not None:
            services.append(
                live_strategy_service
            )

        services.append(
            momentum_trap_service
        )

        services.extend(
            [
                execution_service,
                risk_service,
                risk_event_logger_service,
                monitoring_service,
                health_server_service,
            ]
        )

        orchestrator = Orchestrator(
            event_bus=event_bus,
            task_supervisor=task_supervisor,
            services=services,
        )

        orchestrator_ref["value"] = orchestrator

        return cls(
            config=cfg,
            settings=settings,

            database=database,
            event_bus=event_bus,
            task_supervisor=task_supervisor,

            exchange_manager=exchange_manager,
            exchange_registry=exchange_registry,
            router=router,

            market_source=market_source,
            market_normalizer=market_normalizer,
            market_state_store=market_state_store,
            market_data_service=market_data_service,

            ledger=ledger,
            exposure_engine=exposure_engine,
            portfolio_guard=portfolio_guard,
            state_store=state_store,
            fill_processor=fill_processor,
            pre_trade_risk=pre_trade_risk,
            execution_pipeline=execution_pipeline,
            kill_switch=kill_switch,

            live_strategy=live_strategy,
            live_strategy_service=live_strategy_service,
            momentum_trap_service=momentum_trap_service,

            execution_service=execution_service,
            risk_service=risk_service,
            risk_event_logger_service=risk_event_logger_service,

            runtime_metrics=runtime_metrics,
            monitoring_service=monitoring_service,

            health_aggregator=health_aggregator,
            health_server=health_server,
            health_server_service=health_server_service,

            orchestrator=orchestrator,
        )