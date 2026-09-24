"""
data.py  –  AEGIS PRO v2
Data pipeline: OHLCV fetching, caching, 20+ feature computation engine.

Key fixes over v1:
  - SMA-200 uses min_periods=50 so it doesn't return NaN for first 200 bars
  - ATR relative uses min_periods=20 rolling mean
  - RSI condition for bullish trend is now RSI > 45 (not < 40)
  - Added: MACD histogram, Ichimoku cloud position, Bollinger %B,
    ATR z-score, volume spike, spread %, order-book depth ratios,
    higher-timeframe RSI/ADX carry-through
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import AegisConfig

log = logging.getLogger("aegis.data")


# ---------------------------------------------------------------------------
# Minimal OHLCV cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    data: pd.DataFrame
    fetched_at: float


class OHLCVCache:
    """Thread-safe in-memory OHLCV cache with per-timeframe TTL."""

    _TTL = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
    }

    def __init__(self):
        self._store: Dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        key = f"{symbol}_{tf}"
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry.fetched_at) < self._TTL.get(tf, 60):
                return entry.data.copy()
        return None

    def set(self, symbol: str, tf: str, df: pd.DataFrame) -> None:
        key = f"{symbol}_{tf}"
        with self._lock:
            self._store[key] = _CacheEntry(data=df.copy(), fetched_at=time.time())

    def evict_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                k
                for k, e in self._store.items()
                if (now - e.fetched_at) > max(self._TTL.values()) * 2
            ]
            for k in expired:
                del self._store[k]


ohlcv_cache = OHLCVCache()


# ---------------------------------------------------------------------------
# Raw OHLCV fetch helper (exchange-agnostic; caller passes an exchange object)
# ---------------------------------------------------------------------------

# Minimum bar counts needed for indicators to be meaningful
_MIN_BARS: Dict[str, int] = {
    "1m": 300,
    "5m": 300,
    "15m": 400,  # need 200 for SMA-200, plus warm-up
    "1h": 200,
    "4h": 100,
}


def fetch_ohlcv(
    exchange,
    symbol: str,
    tf: str,
    limit: Optional[int] = None,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV from exchange, return as DataFrame or None.
    Checks cache first. Uses retry decorator at call site.
    """
    cached = ohlcv_cache.get(symbol, tf)
    if cached is not None:
        return cached

    n = limit or _MIN_BARS.get(tf, 300)
    try:
        raw = exchange.fetch_ohlcv(symbol, tf, limit=n)
    except Exception as exc:
        log.warning(f"fetch_ohlcv({symbol}, {tf}): {exc}")
        return None

    if not raw or len(raw) < 20:
        return None

    df = pd.DataFrame(raw, columns=["ts", "o", "h", "l", "c", "v"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    df = df.astype(float)

    ohlcv_cache.set(symbol, tf, df)
    return df


# ---------------------------------------------------------------------------
# Feature engine
# ---------------------------------------------------------------------------


class FeatureEngine:
    """
    Computes a rich feature vector for a given OHLCV DataFrame.

    All computations are vectorised with pandas/numpy – no Python loops.
    Returns a single-row DataFrame representing the LATEST bar's features.
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        df_15m: pd.DataFrame,
        df_1h: Optional[pd.DataFrame] = None,
        df_4h: Optional[pd.DataFrame] = None,
        ob: Optional[dict] = None,  # order-book snapshot: {"bids": [...], "asks": [...]}
    ) -> Optional[pd.Series]:
        """
        Compute all features and return a Series for the latest complete bar.
        Returns None if the DataFrame is too short or has critical NaNs.
        """
        if df_15m is None or len(df_15m) < 60:
            return None

        df = df_15m.copy()
        self._add_classical(df)
        self._add_macd(df)
        self._add_ichimoku(df)
        self._add_microstructure(df)
        self._add_ob_features(df, ob)
        self._add_htf_carry(df, df_1h, df_4h)

        # Drop the last (potentially incomplete) bar, use second-to-last
        row = df.iloc[-2]

        # Critical NaN check
        critical = [
            "rsi",
            "adx",
            "atr_rel",
            "c",
            "bb_upper",
            "bb_lower",
            "sma200",
            "ema_fast",
            "ema_slow",
            "plus_di",
            "minus_di",
        ]
        if any(pd.isna(row.get(col)) for col in critical):
            log.debug("NaN in critical features for latest bar – skipping signal.")
            return None

        return row

    # ------------------------------------------------------------------
    # Classical indicators
    # ------------------------------------------------------------------

    def _add_classical(self, df: pd.DataFrame) -> None:
        p = self.cfg

        # --- RSI (Wilder's EWM) ---
        delta = df["c"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / p.rsi_period, adjust=False).mean()
        loss = (-delta).clip(lower=0).ewm(alpha=1 / p.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-10)
        df["rsi"] = 100 - (100 / (1 + rs))

        # --- ATR (Wilder's EWM) ---
        hl = df["h"] - df["l"]
        hc = (df["h"] - df["c"].shift()).abs()
        lc = (df["l"] - df["c"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df["atr"] = tr.ewm(alpha=1 / p.atr_period, adjust=False).mean()
        # atr_rel: normalised ATR.  min_periods=20 avoids NaN on short windows.
        df["atr_mean"] = df["atr"].rolling(100, min_periods=20).mean()
        df["atr_rel"] = df["atr"] / df["atr_mean"].replace(0, np.nan)

        # ATR z-score over last 50 bars
        atr_std = df["atr"].rolling(50, min_periods=20).std().replace(0, np.nan)
        df["atr_zscore"] = (df["atr"] - df["atr_mean"]) / atr_std

        # --- SMA-200 (min_periods=50 so we get values before 200 bars) ---
        df["sma200"] = df["c"].rolling(200, min_periods=50).mean()

        # --- Bollinger Bands ---
        df["bb_mid"] = df["c"].rolling(p.bb_period).mean()
        bb_std = df["c"].rolling(p.bb_period).std()
        df["bb_upper"] = df["bb_mid"] + p.bb_std * bb_std
        df["bb_lower"] = df["bb_mid"] - p.bb_std * bb_std
        bb_width = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
        # %B: position within band (0=lower, 1=upper)
        df["bb_pct"] = (df["c"] - df["bb_lower"]) / bb_width

        # --- EMAs ---
        df["ema_fast"] = df["c"].ewm(span=p.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["c"].ewm(span=p.ema_slow, adjust=False).mean()
        df["ema_diff"] = (df["ema_fast"] - df["ema_slow"]) / df["c"].replace(0, np.nan)

        # --- ADX / DMI ---
        high_diff = df["h"].diff()
        low_diff = -df["l"].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)
        tr_smooth = tr.ewm(alpha=1 / p.adx_period, adjust=False).mean().replace(0, 1e-10)
        plus_dm_s = (
            pd.Series(plus_dm, index=df.index).ewm(alpha=1 / p.adx_period, adjust=False).mean()
        )
        minus_dm_s = (
            pd.Series(minus_dm, index=df.index).ewm(alpha=1 / p.adx_period, adjust=False).mean()
        )
        df["plus_di"] = 100 * (plus_dm_s / tr_smooth)
        df["minus_di"] = 100 * (minus_dm_s / tr_smooth)
        sum_di = (df["plus_di"] + df["minus_di"]).replace(0, 1e-10)
        dx = 100 * (df["plus_di"] - df["minus_di"]).abs() / sum_di
        df["adx"] = dx.ewm(alpha=1 / p.adx_period, adjust=False).mean()

        # --- Volume features ---
        vol_ma = df["v"].rolling(20, min_periods=5).mean().replace(0, np.nan)
        df["volume_ratio"] = df["v"] / vol_ma
        df["vol_spike"] = (df["volume_ratio"] > 2.0).astype(float)

        # --- Close vs SMA-200 ---
        df["close_vs_sma200"] = (df["c"] / df["sma200"].replace(0, np.nan)) - 1.0

    # ------------------------------------------------------------------
    # MACD
    # ------------------------------------------------------------------

    def _add_macd(self, df: pd.DataFrame) -> None:
        p = self.cfg
        ema12 = df["c"].ewm(span=p.ema_fast, adjust=False).mean()
        ema26 = df["c"].ewm(span=p.ema_slow, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=p.macd_signal, adjust=False).mean()
        df["macd_hist"] = macd_line - signal_line
        # Normalise by ATR so it's comparable across symbols
        df["macd_hist_norm"] = df["macd_hist"] / df["atr"].replace(0, np.nan)

    # ------------------------------------------------------------------
    # Ichimoku Cloud
    # ------------------------------------------------------------------

    def _add_ichimoku(self, df: pd.DataFrame) -> None:
        p = self.cfg

        def donchian_mid(period: int) -> pd.Series:
            return (df["h"].rolling(period).max() + df["l"].rolling(period).min()) / 2

        tenkan = donchian_mid(p.ichimoku_tenkan)
        kijun = donchian_mid(p.ichimoku_kijun)
        senkou_a = ((tenkan + kijun) / 2).shift(p.ichimoku_kijun)
        senkou_b = donchian_mid(p.ichimoku_senkou_b).shift(p.ichimoku_kijun)

        cloud_top = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
        cloud_bot = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)

        # +1 = above cloud, 0 = inside, -1 = below cloud
        conditions = [df["c"] > cloud_top, df["c"] < cloud_bot]
        values = [1.0, -1.0]
        df["close_vs_ichimoku_cloud"] = np.select(conditions, values, default=0.0)
        df["tenkan_kijun_diff"] = (tenkan - kijun) / df["c"].replace(0, np.nan)

    # ------------------------------------------------------------------
    # Microstructure features (derived from OHLCV only; tick-level optional)
    # ------------------------------------------------------------------

    def _add_microstructure(self, df: pd.DataFrame) -> None:
        # Garman-Klass volatility estimator
        log_hl = np.log(df["h"] / df["l"].replace(0, np.nan))
        log_co = np.log(df["c"] / df["o"].replace(0, np.nan))
        df["gk_vol"] = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
        df["gk_vol_ma"] = df["gk_vol"].rolling(20, min_periods=5).mean()

        # Close position within bar's range (0=bottom, 1=top) → trade aggressiveness proxy
        bar_range = (df["h"] - df["l"]).replace(0, np.nan)
        df["close_in_range"] = (df["c"] - df["l"]) / bar_range

        # Candle body ratio
        body = (df["c"] - df["o"]).abs()
        df["body_ratio"] = body / bar_range

    # ------------------------------------------------------------------
    # Order-book features
    # ------------------------------------------------------------------

    def _add_ob_features(self, df: pd.DataFrame, ob: Optional[dict]) -> None:
        if ob and ob.get("bids") and ob.get("asks"):
            bids = ob["bids"]
            asks = ob["asks"]
            bid_vol = sum(b[1] for b in bids[:10])
            ask_vol = sum(a[1] for a in asks[:10])
            total_vol = bid_vol + ask_vol
            df["ob_imbalance"] = bid_vol / ask_vol if ask_vol > 0 else 1.0
            df["bid_depth_ratio"] = bid_vol / total_vol if total_vol > 0 else 0.5
            df["ask_depth_ratio"] = ask_vol / total_vol if total_vol > 0 else 0.5
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else df["c"].iloc[-1]
            df["spread_pct"] = (best_ask - best_bid) / mid if mid > 0 else 0.0
        else:
            # Fall back to NaN (ML will impute or we skip OB-dependent checks)
            for col in ["ob_imbalance", "bid_depth_ratio", "ask_depth_ratio", "spread_pct"]:
                df[col] = np.nan

    # ------------------------------------------------------------------
    # Higher-timeframe carry-through features
    # ------------------------------------------------------------------

    def _add_htf_carry(
        self,
        df: pd.DataFrame,
        df_1h: Optional[pd.DataFrame],
        df_4h: Optional[pd.DataFrame],
    ) -> None:
        # We replicate the most recent 1h/4h values into every 15m row
        # (they're constant within the higher-TF bar but enough for signal gating)
        if df_1h is not None and len(df_1h) >= 30:
            _1h = df_1h.copy()
            self._add_classical(_1h)  # minimal re-compute
            row_1h = _1h.iloc[-2]
            df["rsi_14_1h"] = float(row_1h.get("rsi", np.nan))
            df["adx_1h"] = float(row_1h.get("adx", np.nan))
        else:
            df["rsi_14_1h"] = np.nan
            df["adx_1h"] = np.nan

        if df_4h is not None and len(df_4h) >= 30:
            _4h = df_4h.copy()
            self._add_classical(_4h)
            row_4h = _4h.iloc[-2]
            df["close_vs_sma200_4h"] = float(row_4h.get("close_vs_sma200", np.nan))
            df["rsi_4h"] = float(row_4h.get("rsi", np.nan))
        else:
            df["close_vs_sma200_4h"] = np.nan
            df["rsi_4h"] = np.nan


# ---------------------------------------------------------------------------
# Signal pre-validation (replaces the buggy conditions in original analyze_market)
# ---------------------------------------------------------------------------


def validate_signal_conditions(
    row: pd.Series,
    cfg: AegisConfig,
    btc_bullish: bool,
    symbol: str,
) -> Optional[str]:
    """
    Check basic technical conditions for a trade signal.
    Returns signal type string or None.

    RSI fix: bullish trend requires RSI in [rsi_trend_bull_min, rsi_trend_bull_max]
             (original used RSI < 40 which is contradictory for trend-following)
    """

    def _get(col: str, default=float("nan")) -> float:
        val = row.get(col, default)
        return float("nan") if pd.isna(val) else float(val)

    adx = _get("adx")
    rsi = _get("rsi")
    atr_rel = _get("atr_rel")
    close = _get("c")
    sma200 = _get("sma200")
    ema_diff = _get("ema_diff")
    plus_di = _get("plus_di")
    minus_di = _get("minus_di")
    bb_pct = _get("bb_pct")
    vol_spike = _get("vol_spike")
    rsi_1h = _get("rsi_14_1h")
    adx_1h = _get("adx_1h")
    cloud_pos = _get("close_vs_ichimoku_cloud")
    macd_hist = _get("macd_hist")

    # --- Volatility cap ---
    if not pd.isna(atr_rel) and atr_rel > cfg.volatility_cap:
        return None

    # --- BTC macro filter (skip non-BTC if BTC is bearish) ---
    if symbol != "BTC/USDT" and not btc_bullish:
        return None

    # --- Trend signal (CORRECTED RSI condition) ---
    trend_bull = adx > cfg.adx_threshold and plus_di > minus_di
    rsi_in_trend_range = (
        not pd.isna(rsi) and cfg.rsi_trend_bull_min <= rsi <= cfg.rsi_trend_bull_max
    )
    above_sma200 = (not pd.isna(sma200)) and close > sma200
    ema_cross_up = (not pd.isna(ema_diff)) and ema_diff > 0
    macd_positive = (not pd.isna(macd_hist)) and macd_hist > 0
    adx_1h_ok = pd.isna(adx_1h) or adx_1h > cfg.adx_threshold * 0.8
    above_cloud = pd.isna(cloud_pos) or cloud_pos >= 0

    if (
        trend_bull
        and rsi_in_trend_range
        and above_sma200
        and ema_cross_up
        and macd_positive
        and adx_1h_ok
        and above_cloud
    ):
        return "TREND"

    # --- Range-bounce / oversold signal ---
    range_market = adx < 22
    rsi_oversold = (not pd.isna(rsi)) and rsi < cfg.rsi_range_bear
    near_bb_lower = (not pd.isna(bb_pct)) and bb_pct < 0.10
    rsi_1h_ok = pd.isna(rsi_1h) or rsi_1h < 40

    if range_market and rsi_oversold and near_bb_lower and rsi_1h_ok:
        return "RANGE"

    # --- Breakout signal ---
    breakout = (
        vol_spike > 0 and (not pd.isna(bb_pct)) and bb_pct > 0.95 and adx > 30 and macd_positive
    )
    if breakout:
        return "BREAKOUT"

    return None
