"""
features_extended.py  -  AEGIS PRO v2
Extended feature engine that reaches 60+ features per symbol per timeframe.

Wraps the base FeatureEngine from data.py and adds:
  - Full order-book metrics (8 features) from websocket_ob.py
  - Sentiment & on-chain features (9 features) from sentiment.py
  - Volatility regime features (8 features)
  - Cross-asset correlation features (6 features)
  - Additional microstructure features (7 features)
  - Tick-derived features when tick DB is available (5 features)

Total: 20 (base) + 43 (extended) = 63 features
"""

import logging
import threading
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import linregress  # pip install scipy

from config import AegisConfig
from data import FeatureEngine
from sentiment import get_sentiment_features
from websocket_ob import OrderBookManager, OrderBookSnapshot

log = logging.getLogger("aegis.features_ext")


class ExtendedFeatureEngine(FeatureEngine):
    """
    Drop-in replacement for FeatureEngine with 60+ features.
    Requires ob_manager and optionally tick_db.
    """

    def __init__(
        self,
        cfg: AegisConfig,
        ob_manager: Optional[OrderBookManager] = None,
        tick_db=None,
    ):
        super().__init__(cfg)
        self.ob_manager = ob_manager
        self.tick_db = tick_db

        # Cross-asset price series cache {symbol: Series}
        self._price_cache: Dict[str, pd.Series] = {}
        self._cache_lock = threading.Lock()
        self._corr_matrix: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Override compute() to add extended features
    # ------------------------------------------------------------------

    def compute(
        self,
        df_15m: pd.DataFrame,
        df_1h: Optional[pd.DataFrame] = None,
        df_4h: Optional[pd.DataFrame] = None,
        ob: Optional[dict] = None,
        symbol: str = "",
    ) -> Optional[pd.Series]:
        """
        Full feature computation: 60+ features.
        ob parameter is ignored in favour of ob_manager if available.
        """
        # Base features (20)
        row = super().compute(df_15m, df_1h=df_1h, df_4h=df_4h, ob=ob)
        if row is None:
            return None

        df = df_15m.copy()

        # ---- OB features from WebSocket (8) ----
        if self.ob_manager:
            ob_feats = self.ob_manager.get_ob_features(symbol)
        elif ob:
            snap = self._ob_dict_to_snap(symbol, ob)
            ob_feats = snap.to_feature_dict()
        else:
            ob_feats = {}

        for k, v in ob_feats.items():
            row[k] = v

        # ---- Sentiment & on-chain (9) ----
        sent = get_sentiment_features(symbol)
        for k, v in sent.items():
            row[k] = v

        # ---- Volatility regime (8) ----
        vr = self._volatility_regime_features(df)
        for k, v in vr.items():
            row[k] = v

        # ---- Microstructure extras (7) ----
        ms = self._microstructure_extended(df)
        for k, v in ms.items():
            row[k] = v

        # ---- Cross-asset correlations (6) ----
        corr = self._correlation_features(symbol)
        for k, v in corr.items():
            row[k] = v

        # ---- Tick-derived features (5) ----
        if self.tick_db and symbol:
            tick_feats = self._tick_features(symbol)
            for k, v in tick_feats.items():
                row[k] = v

        return row

    # ------------------------------------------------------------------
    # Volatility regime features (8)
    # ------------------------------------------------------------------

    def _volatility_regime_features(self, df: pd.DataFrame) -> Dict[str, float]:
        c = df["c"]

        # GARCH-lite: ratio of recent vs longer-term realised vol
        ret = c.pct_change().dropna()
        rv_5 = ret.rolling(5).std().iloc[-2] if len(ret) >= 5 else np.nan
        rv_20 = ret.rolling(20).std().iloc[-2] if len(ret) >= 20 else np.nan
        rv_60 = ret.rolling(60).std().iloc[-2] if len(ret) >= 60 else np.nan

        # Volatility regime ratio
        vol_regime = rv_5 / rv_20 if (rv_20 and rv_20 > 0) else 1.0

        # Detrended Price Oscillation (DPO, 20 period)
        half = 20 // 2 + 1
        dpo = c - c.shift(half).rolling(20).mean().shift(-half)
        dpo_v = float(dpo.iloc[-2]) if len(dpo) >= half + 1 else 0.0

        # Hurst exponent (simplified R/S for last 64 bars)
        hurst = self._hurst(c.values[-64:]) if len(c) >= 64 else 0.5

        # Kurtosis of returns (fat tails = crash risk)
        kurt = float(ret.rolling(50).kurt().iloc[-2]) if len(ret) >= 50 else 0.0

        # Skewness of returns
        skew = float(ret.rolling(50).skew().iloc[-2]) if len(ret) >= 50 else 0.0

        # Close-to-close autocorrelation lag-1
        autocorr = float(ret.autocorr(lag=1)) if len(ret) >= 10 else 0.0

        return {
            "vol_regime": float(vol_regime),
            "rv_5": float(rv_5) if not np.isnan(rv_5) else 0.0,
            "rv_60": float(rv_60) if not np.isnan(rv_60) else 0.0,
            "dpo": dpo_v,
            "hurst": hurst,
            "return_kurt": float(np.clip(kurt, -5, 5)),
            "return_skew": float(np.clip(skew, -3, 3)),
            "autocorr_lag1": float(np.clip(autocorr, -1, 1)),
        }

    @staticmethod
    def _hurst(prices: np.ndarray) -> float:
        """
        Simplified Hurst exponent via R/S analysis on log-returns.
        H > 0.5 = trending, H < 0.5 = mean-reverting, H ~ 0.5 = random walk.
        """
        if len(prices) < 16:
            return 0.5
        try:
            log_ret = np.diff(np.log(prices + 1e-10))
            lags = [2, 4, 8, 16]
            rs_vals = []
            for lag in lags:
                chunks = [log_ret[i : i + lag] for i in range(0, len(log_ret) - lag, lag)]
                if not chunks:
                    continue
                rs_list = []
                for chunk in chunks:
                    mean = chunk.mean()
                    dev = (chunk - mean).cumsum()
                    r = dev.max() - dev.min()
                    s = chunk.std()
                    if s > 0:
                        rs_list.append(r / s)
                if rs_list:
                    rs_vals.append((np.log(lag), np.log(np.mean(rs_list))))
            if len(rs_vals) >= 2:
                x = [v[0] for v in rs_vals]
                y = [v[1] for v in rs_vals]
                slope, _, _, _, _ = linregress(x, y)
                return float(np.clip(slope, 0.0, 1.0))
        except Exception:
            pass
        return 0.5

    # ------------------------------------------------------------------
    # Extended microstructure features (7)
    # ------------------------------------------------------------------

    def _microstructure_extended(self, df: pd.DataFrame) -> Dict[str, float]:
        c, h, low, v = df["c"], df["h"], df["low"], df["v"]

        # Amihud illiquidity ratio: |return| / dollar_volume (last 20 bars)
        ret = c.pct_change().abs()
        dv = c * v
        amihud = (ret / dv.replace(0, np.nan)).rolling(20).mean().iloc[-2]

        # Realized bid-ask spread from OHLCV (Roll measure)
        cov_val = float(c.diff().rolling(20).cov(c.diff().shift(1)).iloc[-2])
        roll_spread = 2 * abs(cov_val) ** 0.5 if cov_val < 0 else 0.0

        # Price acceleration (second derivative of price)
        vel = c.diff()
        accel = vel.diff().iloc[-2]

        # Volume-price correlation (20 bar)
        vp_corr = float(v.rolling(20).corr(c).iloc[-2])

        # Tick direction ratio (fraction of bars closing up)
        up_bars = (c.diff() > 0).astype(float).rolling(20).mean().iloc[-2]

        # High-low range expansion vs ATR
        hl_range = h - low
        hl_vs_atr = float(hl_range.iloc[-2] / df["atr"].iloc[-2]) if "atr" in df.columns else 1.0

        # Open-close ratio (body vs total range)
        body = (c - df["o"]).abs()
        oc_ratio = float((body / hl_range.replace(0, np.nan)).iloc[-2])

        return {
            "amihud_illiq": float(amihud) if not np.isnan(amihud) else 0.0,
            "roll_spread": float(roll_spread),
            "price_accel": float(accel) if not np.isnan(accel) else 0.0,
            "vp_corr": float(vp_corr) if not np.isnan(vp_corr) else 0.0,
            "up_bar_ratio": float(up_bars) if not np.isnan(up_bars) else 0.5,
            "hl_vs_atr": float(hl_vs_atr),
            "oc_ratio": float(oc_ratio) if not np.isnan(oc_ratio) else 0.5,
        }

    # ------------------------------------------------------------------
    # Cross-asset correlation features (6)
    # ------------------------------------------------------------------

    def update_price_cache(self, symbol: str, prices: pd.Series) -> None:
        """Call periodically from main loop to keep price cache fresh."""
        with self._cache_lock:
            self._price_cache[symbol] = prices
        self._recompute_corr_matrix()

    def _recompute_corr_matrix(self) -> None:
        with self._cache_lock:
            if len(self._price_cache) < 2:
                return
            df = pd.DataFrame(self._price_cache)
        try:
            ret = df.pct_change().dropna()
            self._corr_matrix = ret.rolling(60, min_periods=20).corr().iloc[-len(df.columns) :]
        except Exception:
            pass

    def _correlation_features(self, symbol: str) -> Dict[str, float]:
        """
        Correlation of this symbol to BTC, ETH, and average of all others.
        Low BTC correlation is desirable (diversification).
        """
        if self._corr_matrix is None:
            return {
                "corr_btc_60": 0.5,
                "corr_eth_60": 0.5,
                "corr_avg_60": 0.5,
                "corr_btc_20": 0.5,
                "corr_eth_20": 0.5,
                "corr_avg_20": 0.5,
            }
        try:
            with self._cache_lock:
                cache = dict(self._price_cache)

            results = {}
            for period, label in [(60, "60"), (20, "20")]:
                sym_prices = cache.get(symbol)
                btc_prices = cache.get("BTC/USDT")
                eth_prices = cache.get("ETH/USDT")

                def _corr(a, b):
                    if a is None or b is None or len(a) < period or len(b) < period:
                        return 0.5
                    a2, b2 = a.align(b, join="inner")
                    r = a2.pct_change().dropna().rolling(period).corr(b2.pct_change().dropna())
                    v = r.iloc[-1]
                    return float(v) if not np.isnan(v) else 0.5

                results[f"corr_btc_{label}"] = _corr(sym_prices, btc_prices)
                results[f"corr_eth_{label}"] = _corr(sym_prices, eth_prices)
                others = [_corr(sym_prices, p) for s, p in cache.items() if s != symbol]
                results[f"corr_avg_{label}"] = float(np.mean(others)) if others else 0.5

            return results
        except Exception:
            return {
                k: 0.5
                for k in [
                    "corr_btc_60",
                    "corr_eth_60",
                    "corr_avg_60",
                    "corr_btc_20",
                    "corr_eth_20",
                    "corr_avg_20",
                ]
            }

    # ------------------------------------------------------------------
    # Tick-derived features (5) from TickDB
    # ------------------------------------------------------------------

    def _tick_features(self, symbol: str) -> Dict[str, float]:
        """
        Compute features from recent raw ticks (last 15 minutes).
        Returns neutral defaults if tick DB unavailable.
        """
        if not self.tick_db:
            return {
                k: 0.0
                for k in [
                    "tick_buy_ratio",
                    "tick_avg_size",
                    "tick_count_15m",
                    "tick_vol_acceleration",
                    "tick_price_std",
                ]
            }
        try:
            since_ms = int((time.time() - 900) * 1000)  # last 15 min
            ticks = self.tick_db.get_ticks(symbol, since_ms, limit=5000)
            if not ticks:
                raise ValueError("no ticks")

            sizes = [t["qty"] for t in ticks]
            prices = [t["price"] for t in ticks]
            buys = [t for t in ticks if t.get("side") in ("buy", "1")]
            buy_ratio = len(buys) / len(ticks)

            # Volume acceleration: compare last 5 min vs previous 10 min
            cutoff = time.time() * 1000 - 300_000
            recent_vol = sum(t["qty"] for t in ticks if t["ts"] >= cutoff)
            older_vol = sum(t["qty"] for t in ticks if t["ts"] < cutoff)
            vol_accel = (recent_vol / max(older_vol, 1e-10)) - 1.0

            return {
                "tick_buy_ratio": float(buy_ratio),
                "tick_avg_size": float(np.mean(sizes)) if sizes else 0.0,
                "tick_count_15m": float(len(ticks)) / 1000.0,  # normalise
                "tick_vol_acceleration": float(np.clip(vol_accel, -2, 2)),
                "tick_price_std": float(np.std(prices)) if prices else 0.0,
            }
        except Exception as exc:
            log.debug(f"Tick features failed ({symbol}): {exc}")
            return {
                k: 0.0
                for k in [
                    "tick_buy_ratio",
                    "tick_avg_size",
                    "tick_count_15m",
                    "tick_vol_acceleration",
                    "tick_price_std",
                ]
            }

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _ob_dict_to_snap(symbol: str, ob: dict) -> OrderBookSnapshot:
        from websocket_ob import OrderBookSnapshot

        return OrderBookSnapshot(
            symbol=symbol,
            bids=[(float(p), float(q)) for p, q in ob.get("bids", [])[:20]],
            asks=[(float(p), float(q)) for p, q in ob.get("asks", [])[:20]],
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Feature name list (for ML training)
    # ------------------------------------------------------------------

    @staticmethod
    def all_feature_names() -> List[str]:
        """Return all 63 feature column names for model training."""
        base = [
            "rsi",
            "adx",
            "atr_rel",
            "atr_zscore",
            "ema_diff",
            "volume_ratio",
            "vol_spike",
            "close_vs_sma200",
            "bb_pct",
            "macd_hist",
            "macd_hist_norm",
            "plus_di",
            "minus_di",
            "close_vs_ichimoku_cloud",
            "tenkan_kijun_diff",
            "gk_vol",
            "gk_vol_ma",
            "close_in_range",
            "body_ratio",
            "rsi_14_1h",
            "adx_1h",
            "close_vs_sma200_4h",
            "rsi_4h",
        ]
        ob = [
            "ob_imbalance",
            "bid_depth_ratio",
            "ask_depth_ratio",
            "spread_pct",
            "vwap_spread",
            "ob_toxicity",
            "price_impact_buy",
            "price_impact_sell",
        ]
        sentiment = [
            "fear_greed",
            "fear_greed_norm",
            "btc_dominance",
            "mktcap_change_24h",
            "funding_rate_btc",
            "funding_rate_sym",
            "btc_tx_count_norm",
            "btc_hash_rate_norm",
            "nvt_proxy_norm",
        ]
        vol_regime = [
            "vol_regime",
            "rv_5",
            "rv_60",
            "dpo",
            "hurst",
            "return_kurt",
            "return_skew",
            "autocorr_lag1",
        ]
        microstructure = [
            "amihud_illiq",
            "roll_spread",
            "price_accel",
            "vp_corr",
            "up_bar_ratio",
            "hl_vs_atr",
            "oc_ratio",
        ]
        correlation = [
            "corr_btc_60",
            "corr_eth_60",
            "corr_avg_60",
            "corr_btc_20",
            "corr_eth_20",
            "corr_avg_20",
        ]
        tick = [
            "tick_buy_ratio",
            "tick_avg_size",
            "tick_count_15m",
            "tick_vol_acceleration",
            "tick_price_std",
        ]
        all_feats = base + ob + sentiment + vol_regime + microstructure + correlation + tick
        return all_feats  # 23 + 8 + 9 + 8 + 7 + 6 + 5 = 66 features
