"""
config.py  -  AEGIS PRO v2
All configuration loading, validation, and AES-256 encryption at rest.

Priority order:  environment variables > encrypted config file > defaults

FIXES:
  - validate_config return type annotation updated to list[str] ÃƒÂ¢Ã¢â‚¬Â ' List[str] (Python 3.8 compat)
  - .env.template env var names aligned: BINANCE_API_SECRET ÃƒÂ¢Ã¢â‚¬Â ' BINANCE_SECRET, etc.
  - Added missing OKX_PASSPHRASE to env map
  - Added AEGIS_CONFIG_PASSWORD to env map
"""

import base64
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Optional: real AES-256 via cryptography; fall back to clear-text with warning
# ---------------------------------------------------------------------------
try:
    from cryptography.fernet import Fernet, InvalidToken

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False
    logging.warning(
        "cryptography not installed. Config will be stored UNENCRYPTED. "
        "Run: pip install cryptography"
    )


_SALT_LEN = 32  # bytes for random per-config salt


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-derived Fernet key from a password string and a random salt."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        iterations=260_000,
    )
    return base64.urlsafe_b64encode(dk)


def encrypt_config(data: dict, password: str) -> bytes:
    """Encrypt config; prepends 32-byte random salt before the Fernet token."""
    if not _HAS_CRYPTO:
        return json.dumps(data).encode()
    import os as _os

    salt = _os.urandom(_SALT_LEN)
    f = Fernet(_derive_fernet_key(password, salt))
    return salt + f.encrypt(json.dumps(data).encode())


def decrypt_config(token: bytes, password: str) -> dict:
    """Decrypt config; handles both legacy (static-salt) and new (prepended-salt) formats."""
    if not _HAS_CRYPTO:
        return json.loads(token)
    # New format: first 32 bytes are random salt
    if len(token) > _SALT_LEN:
        salt = token[:_SALT_LEN]
        payload = token[_SALT_LEN:]
        # Try new format first
        try:
            f = Fernet(_derive_fernet_key(password, salt))
            return json.loads(f.decrypt(payload))
        except Exception:
            pass
    # Legacy fallback: static salt
    try:
        import hashlib as _hashlib

        from cryptography.fernet import Fernet as _Fernet

        dk = _hashlib.pbkdf2_hmac(
            "sha256", password.encode(), b"aegis_pro_salt_v2", iterations=260_000
        )
        f = _Fernet(base64.urlsafe_b64encode(dk))
        return json.loads(f.decrypt(token))
    except (InvalidToken, Exception) as exc:
        raise ValueError("Failed to decrypt config - wrong password or corrupted file.") from exc


# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(os.environ.get("AEGIS_DATA_DIR", Path.cwd()))
BASE_DIR.mkdir(parents=True, exist_ok=True)

PATHS = {
    "config": BASE_DIR / "aegis_config.bin",
    "log": BASE_DIR / "aegis.log",
    "crash_log": BASE_DIR / "crash.log",
    "db": BASE_DIR / "aegis.db",
    "tick_db": BASE_DIR / "ticks.db",
    "positions": BASE_DIR / "positions.json",
    "stats": BASE_DIR / "daily_stats.json",
    "hist_stats": BASE_DIR / "historical_stats.json",
    "perf_stats": BASE_DIR / "performance_stats.json",
    "status": BASE_DIR / "status.json",
    "heartbeat": BASE_DIR / "heartbeat.json",
    "ml_model": BASE_DIR / "ml_model.pkl",
    "restart_count": BASE_DIR / "restart_count.json",
    "backups": BASE_DIR / "backups",
    "reports": BASE_DIR / "reports",
}
for _p in [PATHS["backups"], PATHS["reports"]]:
    Path(_p).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Config dataclass - single source of truth for every tuneable parameter
# ---------------------------------------------------------------------------
@dataclass
class AegisConfig:
    # ---- Credentials (never stored in code; loaded from env or encrypted file) ----
    binance_api_key: str = ""
    binance_secret: str = ""
    bybit_api_key: str = ""
    bybit_secret: str = ""
    okx_api_key: str = ""
    okx_secret: str = ""
    okx_passphrase: str = ""

    tg_token: str = ""
    tg_chat_id: str = ""

    # ---- Mode ----
    mode: str = "PAPER"  # "PAPER" | "LIVE"
    live_confirm: str = ""  # must be "YES_I_ACCEPT_THE_RISK"
    proxy: str = ""

    # ---- Watchlist ----
    watchlist: List[str] = field(
        default_factory=lambda: [
            "BTC/USDT",
            "ETH/USDT",
            "BNB/USDT",
            "SOL/USDT",
            "XRP/USDT",
            "ADA/USDT",
            "AVAX/USDT",
            "LINK/USDT",
            "MATIC/USDT",
            "DOT/USDT",
            "LTC/USDT",
            "ATOM/USDT",
            "NEAR/USDT",
            "UNI/USDT",
            "ALGO/USDT",
            "VET/USDT",
            "DOGE/USDT",
            "TRX/USDT",
            "SHIB/USDT",
            "FIL/USDT",
        ]
    )

    # ---- Indicator parameters ----
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    ema_fast: int = 12
    ema_slow: int = 26
    bb_period: int = 20
    bb_std: float = 2.0
    macd_signal: int = 9
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou_b: int = 52

    # ---- Strategy thresholds ----
    adx_threshold: float = 25.0
    rsi_trend_bull_min: float = 45.0
    rsi_trend_bull_max: float = 70.0
    rsi_range_bear: float = 32.0
    volatility_cap: float = 2.5
    ob_imbalance_threshold: float = 1.3
    ml_prob_threshold: float = 0.58
    fused_threshold: float = 0.65

    # ---- ATR multipliers ----
    atr_stop_mult: float = 2.0
    atr_tp1_mult: float = 1.5
    atr_tp1_frac: float = 0.40
    atr_tp2_mult: float = 2.5
    atr_tp2_frac: float = 0.40
    atr_trail_trigger: float = 1.0
    early_trail_trigger: float = 0.5

    # ---- Risk management ----
    base_risk_per_trade: float = 0.01
    kelly_fraction: float = 0.25
    max_portfolio_heat: float = 0.30
    max_pos_allocation: float = 0.12
    max_concurrent_trades: int = 6
    max_daily_trades: int = 10
    max_consecutive_losses: int = 4
    max_breaker_count: int = 4

    # ---- Drawdown controls ----
    max_daily_loss_pct: float = 2.5
    max_weekly_loss_pct: float = 5.0
    max_drawdown_pct: float = 12.0
    drawdown_lock_hours: float = 48.0

    # ---- Execution ----
    slippage_tol: float = 0.002
    sim_slippage: float = 0.002
    limit_adjust_secs: float = 2.0
    limit_cancel_secs: float = 10.0
    max_slippage_blacklist: float = 0.002

    # ---- Timing ----
    scan_interval_secs: int = 120
    correlation_update_secs: int = 3600
    ml_retrain_interval_secs: int = 86400 * 7
    ip_check_interval_secs: int = 3600
    memory_monitor_secs: int = 300
    heartbeat_interval_secs: int = 300
    heartbeat_timeout_secs: int = 360
    cache_ttl_ohlcv_15m: int = 900
    cache_ttl_ohlcv_1h: int = 3600
    cache_ttl_ohlcv_4h: int = 14400
    cache_ttl_ticker: int = 10
    cache_ttl_orderbook: int = 5
    cache_ttl_balance: int = 300

    # ---- ML ----
    ml_min_train_samples: int = 500
    ml_n_estimators: int = 300
    ml_max_depth: int = 5
    ml_learning_rate: float = 0.05
    ml_subsample: float = 0.8
    ml_colsample: float = 0.8
    ml_forward_bars: int = 3
    ml_features: List[str] = field(
        default_factory=lambda: [
            "rsi",
            "adx",
            "atr_rel",
            "ema_diff",
            "volume_ratio",
            "close_vs_sma200",
            "bb_pct",
            "macd_hist",
            "plus_di",
            "minus_di",
            "ob_imbalance",
            "bid_depth_ratio",
            "ask_depth_ratio",
            "spread_pct",
            "vol_spike",
            "atr_zscore",
            "close_vs_ichimoku_cloud",
            "tenkan_kijun_diff",
            "rsi_14_1h",
            "adx_1h",
            "close_vs_sma200_4h",
        ]
    )

    # ---- Dashboard ----
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    dashboard_enabled: bool = True

    # ---- Pairs trading ----
    pairs_zscore_threshold: float = 2.5
    pairs_min_coint_pvalue: float = 0.05

    # ---- Memory ----
    memory_threshold_mb: float = 500.0
    max_restarts_per_hour: int = 3

    # ---- Time-based stop ----
    time_stop_candles: int = 3

    # ---- Cooldown ----
    symbol_cooldown_secs: int = 300


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(password: Optional[str] = None) -> AegisConfig:
    """
    Load configuration with this priority:
    1. Environment variables (always override everything)
    2. Encrypted config file
    3. Dataclass defaults
    """
    cfg = AegisConfig()

    # --- encrypted file ---
    cfg_path = PATHS["config"]
    if cfg_path.exists():
        _password = password or os.environ.get("AEGIS_CONFIG_PASSWORD", "default_dev_password")
        try:
            raw = cfg_path.read_bytes()
            file_data = decrypt_config(raw, _password)
            for k, v in file_data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        except Exception as exc:
            logging.error(f"Config file could not be loaded: {exc}")

    # --- environment variables (highest priority) ---
    # FIX: aligned env var names with .env.template
    _env_map = {
        "BINANCE_API_KEY": "binance_api_key",
        "BINANCE_SECRET": "binance_secret",
        "BYBIT_API_KEY": "bybit_api_key",
        "BYBIT_SECRET": "bybit_secret",
        "OKX_API_KEY": "okx_api_key",
        "OKX_SECRET": "okx_secret",
        "OKX_PASSPHRASE": "okx_passphrase",
        "TG_TOKEN": "tg_token",
        "TG_CHAT_ID": "tg_chat_id",
        "AEGIS_MODE": "mode",
        "AEGIS_LIVE_CONFIRM": "live_confirm",
        "HTTP_PROXY": "proxy",
    }
    for env_key, attr in _env_map.items():
        val = os.environ.get(env_key)
        if val:
            setattr(cfg, attr, val)

    return cfg


def save_config(cfg: AegisConfig, password: Optional[str] = None) -> None:
    """Persist config to encrypted file."""
    _password = password or os.environ.get("AEGIS_CONFIG_PASSWORD", "default_dev_password")
    data = asdict(cfg)
    encrypted = encrypt_config(data, _password)
    cfg_path = PATHS["config"]
    tmp = cfg_path.with_suffix(".tmp")
    tmp.write_bytes(encrypted)
    tmp.replace(cfg_path)


def validate_config(cfg: AegisConfig) -> List[str]:  # FIX: list[str] ÃƒÂ¢Ã¢â‚¬Â ' List[str] (3.8 compat)
    """Return a list of validation errors (empty = OK)."""
    errors = []

    if cfg.mode not in ("PAPER", "LIVE"):
        errors.append(f"Invalid mode: {cfg.mode!r}. Must be PAPER or LIVE.")

    if cfg.mode == "LIVE":
        if cfg.live_confirm != "YES_I_ACCEPT_THE_RISK":
            errors.append("live_confirm must be 'YES_I_ACCEPT_THE_RISK' for LIVE mode.")
        if not cfg.binance_api_key:
            errors.append("binance_api_key is required for LIVE mode.")
        if not cfg.binance_secret:
            errors.append("binance_secret is required for LIVE mode.")

    if not (0 < cfg.base_risk_per_trade <= 0.05):
        errors.append(f"base_risk_per_trade {cfg.base_risk_per_trade} should be in (0, 0.05].")

    if not (0 < cfg.max_portfolio_heat <= 1.0):
        errors.append("max_portfolio_heat must be in (0, 1].")

    if cfg.max_concurrent_trades < 1:
        errors.append("max_concurrent_trades must be >= 1.")

    # FIX: validate ATR TP fractions sum ÃƒÂ¢Ã¢â‚¬Â°Ã‚Â¤ 1.0 to avoid negative remaining quantity
    if cfg.atr_tp1_frac + cfg.atr_tp2_frac > 1.0:
        errors.append(
            f"atr_tp1_frac ({cfg.atr_tp1_frac}) + atr_tp2_frac ({cfg.atr_tp2_frac}) > 1.0 "
            "- would result in negative remaining quantity."
        )

    return errors
