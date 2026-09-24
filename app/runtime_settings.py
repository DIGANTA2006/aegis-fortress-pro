import os
from dataclasses import dataclass

from config import AegisConfig


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)

    if raw is None or raw == "":
        return float(default)

    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid float") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)

    if raw is None or raw == "":
        return int(default)

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid integer") from exc


def _str_env(name: str, default: str) -> str:
    raw = os.environ.get(name)

    return raw if raw else default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)

    if raw is None or raw == "":
        return default

    normalized = raw.strip().lower()

    if normalized in {"1", "true", "yes", "y", "on"}:
        return True

    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(
        f"{name} must be a boolean-like value"
    )


def _tuple_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.environ.get(name)

    if raw is None or raw == "":
        return default

    return tuple(
        item.strip()
        for item in raw.split(",")
        if item.strip()
    )


def _symbols_from_config(cfg: AegisConfig) -> tuple[str, ...]:
    raw_env = os.environ.get("AEGIS_MARKET_SYMBOLS")

    if raw_env:
        return tuple(
            item.strip()
            for item in raw_env.split(",")
            if item.strip()
        )

    candidate_names = (
        "symbols",
        "markets",
        "trading_symbols",
    )

    for name in candidate_names:
        value = getattr(cfg, name, None)

        if isinstance(value, (list, tuple, set)):
            symbols = tuple(
                str(item).strip()
                for item in value
                if str(item).strip()
            )

            if symbols:
                return symbols

    single_symbol = getattr(cfg, "symbol", None)

    if single_symbol:
        return (str(single_symbol).strip(),)

    return tuple()


@dataclass
class RuntimeSettings:
    reference_equity: float
    max_gross_exposure: float
    max_net_exposure: float
    max_symbol_weight: float
    max_order_notional: float
    max_daily_loss: float
    max_drawdown_pct: float

    market_symbols: tuple[str, ...]
    market_poll_interval_seconds: float
    orderbook_depth: int
    market_fetch_concurrency: int
    market_stale_after_seconds: float

    database_path: str
    metrics_port: int
    monitoring_interval_seconds: float

    health_host: str
    health_port: int
    health_snapshot_interval_seconds: float

    live_strategy_enabled: bool
    strategy_target_notional: float
    strategy_max_position_notional: float
    strategy_rolling_window: int
    strategy_min_observations: int
    strategy_entry_zscore: float
    strategy_exit_zscore: float
    strategy_imbalance_threshold: float
    strategy_max_spread_bps: float
    strategy_cooldown_seconds: float
    strategy_order_type: str
    strategy_min_order_notional: float
    strategy_take_profit_bps: float
    strategy_stop_loss_bps: float
    strategy_min_profit_after_fee_bps: float
    strategy_max_hold_seconds: float
    strategy_symbol_cooldown_after_exit_seconds: float
    strategy_loss_cooldown_seconds: float
    strategy_bad_symbol_drop_bps: float

    auto_symbol_discovery_enabled: bool
    symbol_discovery_quote: str
    symbol_discovery_max_symbols: int
    symbol_discovery_min_quote_volume: float
    symbol_discovery_min_change_pct: float
    symbol_discovery_max_change_pct: float
    symbol_discovery_max_spread_bps: float
    symbol_discovery_excluded_symbols: tuple[str, ...]
    symbol_discovery_refresh_seconds: float

    @classmethod
    def from_config(cls, cfg: AegisConfig) -> "RuntimeSettings":
        reference_equity = _float_env(
            "AEGIS_REFERENCE_EQUITY",
            10000.0,
        )

        if reference_equity <= 0:
            raise ValueError("AEGIS_REFERENCE_EQUITY must be positive")

        default_gross = reference_equity * cfg.max_portfolio_heat
        default_net = default_gross
        default_max_order = reference_equity * cfg.max_pos_allocation
        default_daily_loss = reference_equity * (cfg.max_daily_loss_pct / 100.0)

        if cfg.max_portfolio_heat > 0:
            default_symbol_weight = min(
                1.0,
                cfg.max_pos_allocation / cfg.max_portfolio_heat,
            )
        else:
            default_symbol_weight = 0.40

        return cls(
            reference_equity=reference_equity,
            max_gross_exposure=_float_env(
                "AEGIS_MAX_GROSS_EXPOSURE",
                default_gross,
            ),
            max_net_exposure=_float_env(
                "AEGIS_MAX_NET_EXPOSURE",
                default_net,
            ),
            max_symbol_weight=_float_env(
                "AEGIS_MAX_SYMBOL_WEIGHT",
                default_symbol_weight,
            ),
            max_order_notional=_float_env(
                "AEGIS_MAX_ORDER_NOTIONAL",
                default_max_order,
            ),
            max_daily_loss=_float_env(
                "AEGIS_MAX_DAILY_LOSS",
                default_daily_loss,
            ),
            max_drawdown_pct=_float_env(
                "AEGIS_MAX_DRAWDOWN_PCT",
                cfg.max_drawdown_pct,
            ),
            market_symbols=_symbols_from_config(cfg),
            market_poll_interval_seconds=_float_env(
                "AEGIS_MARKET_POLL_INTERVAL_SECONDS",
                2.0,
            ),
            orderbook_depth=_int_env(
                "AEGIS_ORDERBOOK_DEPTH",
                20,
            ),
            market_fetch_concurrency=_int_env(
                "AEGIS_MARKET_FETCH_CONCURRENCY",
                8,
            ),
            market_stale_after_seconds=_float_env(
                "AEGIS_MARKET_STALE_AFTER_SECONDS",
                30.0,
            ),
            database_path=_str_env(
                "AEGIS_DATABASE_PATH",
                "data/aegis_runtime.db",
            ),
            metrics_port=_int_env(
                "AEGIS_METRICS_PORT",
                9000,
            ),
            monitoring_interval_seconds=_float_env(
                "AEGIS_MONITORING_INTERVAL_SECONDS",
                5.0,
            ),
            health_host=_str_env(
                "AEGIS_HEALTH_HOST",
                "127.0.0.1",
            ),
            health_port=_int_env(
                "AEGIS_HEALTH_PORT",
                8080,
            ),
            health_snapshot_interval_seconds=_float_env(
                "AEGIS_HEALTH_SNAPSHOT_INTERVAL_SECONDS",
                30.0,
            ),
            live_strategy_enabled=_bool_env(
                "AEGIS_LIVE_STRATEGY_ENABLED",
                True,
            ),
            strategy_target_notional=_float_env(
                "AEGIS_STRATEGY_TARGET_NOTIONAL",
                100.0,
            ),
            strategy_max_position_notional=_float_env(
                "AEGIS_STRATEGY_MAX_POSITION_NOTIONAL",
                300.0,
            ),
            strategy_rolling_window=_int_env(
                "AEGIS_STRATEGY_ROLLING_WINDOW",
                30,
            ),
            strategy_min_observations=_int_env(
                "AEGIS_STRATEGY_MIN_OBSERVATIONS",
                20,
            ),
            strategy_entry_zscore=_float_env(
                "AEGIS_STRATEGY_ENTRY_ZSCORE",
                1.25,
            ),
            strategy_exit_zscore=_float_env(
                "AEGIS_STRATEGY_EXIT_ZSCORE",
                0.25,
            ),
            strategy_imbalance_threshold=_float_env(
                "AEGIS_STRATEGY_IMBALANCE_THRESHOLD",
                0.20,
            ),
            strategy_max_spread_bps=_float_env(
                "AEGIS_STRATEGY_MAX_SPREAD_BPS",
                12.0,
            ),
            strategy_cooldown_seconds=_float_env(
                "AEGIS_STRATEGY_COOLDOWN_SECONDS",
                20.0,
            ),
            strategy_order_type=_str_env(
                "AEGIS_STRATEGY_ORDER_TYPE",
                "MARKET",
            ).upper(),
            strategy_min_order_notional=_float_env(
                "AEGIS_STRATEGY_MIN_ORDER_NOTIONAL",
                5.5,
            ),
            strategy_take_profit_bps=_float_env(
                "AEGIS_STRATEGY_TAKE_PROFIT_BPS",
                60.0,
            ),
            strategy_stop_loss_bps=_float_env(
                "AEGIS_STRATEGY_STOP_LOSS_BPS",
                35.0,
            ),
            strategy_min_profit_after_fee_bps=_float_env(
                "AEGIS_STRATEGY_MIN_PROFIT_AFTER_FEE_BPS",
                18.0,
            ),
            strategy_max_hold_seconds=_float_env(
                "AEGIS_STRATEGY_MAX_HOLD_SECONDS",
                900.0,
            ),
            strategy_symbol_cooldown_after_exit_seconds=_float_env(
                "AEGIS_STRATEGY_SYMBOL_COOLDOWN_AFTER_EXIT_SECONDS",
                900.0,
            ),
            strategy_loss_cooldown_seconds=_float_env(
                "AEGIS_STRATEGY_LOSS_COOLDOWN_SECONDS",
                3600.0,
            ),
            strategy_bad_symbol_drop_bps=_float_env(
                "AEGIS_STRATEGY_BAD_SYMBOL_DROP_BPS",
                1200.0,
            ),
            auto_symbol_discovery_enabled=_bool_env(
                "AEGIS_AUTO_SYMBOL_DISCOVERY",
                False,
            ),
            symbol_discovery_quote=_str_env(
                "AEGIS_SYMBOL_DISCOVERY_QUOTE",
                "USDT",
            ).upper(),
            symbol_discovery_max_symbols=_int_env(
                "AEGIS_SYMBOL_DISCOVERY_MAX_SYMBOLS",
                6,
            ),
            symbol_discovery_min_quote_volume=_float_env(
                "AEGIS_SYMBOL_DISCOVERY_MIN_QUOTE_VOLUME",
                1000000.0,
            ),
            symbol_discovery_min_change_pct=_float_env(
                "AEGIS_SYMBOL_DISCOVERY_MIN_CHANGE_PCT",
                0.0,
            ),
            symbol_discovery_max_change_pct=_float_env(
                "AEGIS_SYMBOL_DISCOVERY_MAX_CHANGE_PCT",
                18.0,
            ),
            symbol_discovery_max_spread_bps=_float_env(
                "AEGIS_SYMBOL_DISCOVERY_MAX_SPREAD_BPS",
                20.0,
            ),
            symbol_discovery_excluded_symbols=_tuple_env(
                "AEGIS_SYMBOL_DISCOVERY_EXCLUDED_SYMBOLS",
                (),
            ),
            symbol_discovery_refresh_seconds=_float_env(
                "AEGIS_SYMBOL_DISCOVERY_REFRESH_SECONDS",
                1800.0,
            ),
        )

    def validate(self) -> None:
        if self.max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be positive")

        if self.max_net_exposure <= 0:
            raise ValueError("max_net_exposure must be positive")

        if not 0 < self.max_symbol_weight <= 1:
            raise ValueError("max_symbol_weight must be in (0, 1]")

        if self.max_order_notional <= 0:
            raise ValueError("max_order_notional must be positive")

        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")

        if self.max_drawdown_pct <= 0:
            raise ValueError("max_drawdown_pct must be positive")

        if self.market_poll_interval_seconds <= 0:
            raise ValueError("market_poll_interval_seconds must be positive")

        if self.orderbook_depth <= 0:
            raise ValueError("orderbook_depth must be positive")

        if self.market_fetch_concurrency <= 0:
            raise ValueError("market_fetch_concurrency must be positive")

        if self.market_stale_after_seconds <= 0:
            raise ValueError("market_stale_after_seconds must be positive")

        if self.metrics_port <= 0:
            raise ValueError("metrics_port must be positive")

        if self.health_port <= 0:
            raise ValueError("health_port must be positive")

        if self.monitoring_interval_seconds <= 0:
            raise ValueError("monitoring_interval_seconds must be positive")

        if self.health_snapshot_interval_seconds <= 0:
            raise ValueError("health_snapshot_interval_seconds must be positive")

        if self.strategy_target_notional <= 0:
            raise ValueError("strategy_target_notional must be positive")

        if self.strategy_max_position_notional <= 0:
            raise ValueError("strategy_max_position_notional must be positive")

        if self.strategy_rolling_window < 5:
            raise ValueError("strategy_rolling_window must be at least 5")

        if self.strategy_min_observations < 5:
            raise ValueError("strategy_min_observations must be at least 5")

        if self.strategy_min_observations > self.strategy_rolling_window:
            raise ValueError(
                "strategy_min_observations cannot exceed strategy_rolling_window"
            )

        if self.strategy_entry_zscore <= 0:
            raise ValueError("strategy_entry_zscore must be positive")

        if self.strategy_exit_zscore < 0:
            raise ValueError("strategy_exit_zscore cannot be negative")

        if self.strategy_exit_zscore >= self.strategy_entry_zscore:
            raise ValueError(
                "strategy_exit_zscore must be smaller than strategy_entry_zscore"
            )

        if not 0 < self.strategy_imbalance_threshold <= 1:
            raise ValueError(
                "strategy_imbalance_threshold must be in (0, 1]"
            )

        if self.strategy_max_spread_bps <= 0:
            raise ValueError("strategy_max_spread_bps must be positive")

        if self.strategy_cooldown_seconds < 0:
            raise ValueError("strategy_cooldown_seconds cannot be negative")

        if self.strategy_order_type not in {"MARKET", "LIMIT"}:
            raise ValueError(
                "strategy_order_type must be MARKET or LIMIT"
            )