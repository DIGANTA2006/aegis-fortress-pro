"""
models.py  –  AEGIS PRO v2
XGBoost supervised ML, dynamic signal-fusion (weighted voting),
basic pairs-trading cointegration check.

Replaces v1's LogisticRegression with XGBoost and adds:
  - Walk-forward cross-validation (no lookahead)
  - Per-model Sharpe-based dynamic weights
  - Sigmoid fused probability
"""

import logging
import pickle
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import PATHS, AegisConfig
from utils import safe_div, sigmoid

log = logging.getLogger("aegis.models")


# ---------------------------------------------------------------------------
# Try optional heavy deps gracefully
# ---------------------------------------------------------------------------

try:
    import xgboost as xgb

    _HAS_XGB = True
except ImportError:
    _HAS_XGB = False
    log.warning("xgboost not installed. ML signal disabled. pip install xgboost")

try:
    from statsmodels.tsa.stattools import coint

    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False
    log.warning("statsmodels not installed. Pairs signal disabled. pip install statsmodels")


# ---------------------------------------------------------------------------
# XGBoost classifier wrapper
# ---------------------------------------------------------------------------


class XGBSignalModel:
    """
    Binary classifier: P(profitable in next N bars after fees & slippage).

    Target construction:
        y = 1  if  (close[t+N] - close[t]) / close[t]  >  fee_threshold
        y = 0  otherwise

    Uses walk-forward splits to avoid lookahead bias.
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        self.model: Optional["xgb.XGBClassifier"] = None
        self.feature_cols: List[str] = cfg.ml_features
        self._lock = threading.Lock()
        self.last_trained: float = 0.0
        self.train_accuracy: float = 0.0
        self.oos_accuracy: float = 0.0

    # ------------------------------------------------------------------

    def build_dataset(
        self, frames: Dict[str, pd.DataFrame]
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        frames: {symbol: feature_df} – each row already has all feature columns.
        Returns X, y arrays ready for training.
        """
        X_parts, y_parts = [], []
        fee = 0.001 * 2  # entry + exit taker fee (0.1% each)
        slip = self.cfg.sim_slippage * 2
        threshold = fee + slip
        N = self.cfg.ml_forward_bars

        for _sym, df in frames.items():
            if df is None or len(df) < N + 10:
                continue

            feat_cols = [c for c in self.feature_cols if c in df.columns]
            if not feat_cols:
                continue

            sub = df[feat_cols + ["c"]].dropna()
            if len(sub) < N + 5:
                continue

            # Forward return
            fwd = sub["c"].shift(-N) / sub["c"] - 1
            y = (fwd > threshold).astype(int)

            # Drop last N rows (future not yet known)
            sub = sub.iloc[:-N]
            y = y.iloc[:-N]

            X_parts.append(sub[feat_cols].values)
            y_parts.append(y.values)

        if not X_parts:
            return None, None

        X = np.vstack(X_parts)
        y = np.concatenate(y_parts)

        # Remove rows with NaN in features
        mask = ~np.isnan(X).any(axis=1)
        return X[mask], y[mask]

    # ------------------------------------------------------------------

    def train(self, frames: Dict[str, pd.DataFrame]) -> bool:
        """
        Walk-forward training: last 20% of data is held out as OOS test.
        Returns True if training succeeded.
        """
        if not _HAS_XGB:
            return False

        X, y = self.build_dataset(frames)
        if X is None or len(X) < self.cfg.ml_min_train_samples:
            log.warning(
                f"Not enough data for XGB training: "
                f"{len(X) if X is not None else 0} samples < {self.cfg.ml_min_train_samples}"
            )
            return False

        # Walk-forward split (time-ordered data; last 20% = OOS)
        split = int(len(X) * 0.80)
        X_train, X_oos = X[:split], X[split:]
        y_train, y_oos = y[:split], y[split:]

        cfg = self.cfg
        clf = xgb.XGBClassifier(
            n_estimators=cfg.ml_n_estimators,
            max_depth=cfg.ml_max_depth,
            learning_rate=cfg.ml_learning_rate,
            subsample=cfg.ml_subsample,
            colsample_bytree=cfg.ml_colsample,
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(
            X_train,
            y_train,
            eval_set=[(X_oos, y_oos)],
            verbose=False,
        )

        train_acc = clf.score(X_train, y_train)
        oos_acc = clf.score(X_oos, y_oos) if len(X_oos) > 0 else 0.0

        log.info(
            f"XGB trained: {len(X_train)} train samples, "
            f"train acc={train_acc:.3f}, OOS acc={oos_acc:.3f}"
        )

        with self._lock:
            self.model = clf
            self.train_accuracy = train_acc
            self.oos_accuracy = oos_acc
            self.last_trained = time.time()
            first_key = next(iter(frames), None)
            if first_key is not None:
                available = frames[first_key].columns.tolist()
                self.feature_cols = [
                    c for c in cfg.ml_features if c in available
                ] or cfg.ml_features
            else:
                self.feature_cols = cfg.ml_features

        self._save()
        return True

    # ------------------------------------------------------------------

    def predict(self, row: pd.Series) -> float:
        """Return P(profitable) in [0, 1]. Returns 0.5 if model unavailable."""
        with self._lock:
            if self.model is None:
                return 0.5
            feat_cols = [c for c in self.feature_cols if c in row.index]
            if not feat_cols:
                return 0.5
            X = np.array([float(row.get(c, np.nan)) for c in feat_cols]).reshape(1, -1)
            if np.isnan(X).any():
                # Impute NaN with 0 (centred after normalisation)
                X = np.nan_to_num(X, nan=0.0)
            try:
                prob = float(self.model.predict_proba(X)[0][1])
                return prob
            except Exception as exc:
                log.warning(f"XGB inference error: {exc}")
                return 0.5

    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            with open(PATHS["ml_model"], "wb") as f:
                pickle.dump(
                    {
                        "model": self.model,
                        "feature_cols": self.feature_cols,
                        "oos_acc": self.oos_accuracy,
                    },
                    f,
                )
            log.info("ML model saved.")
        except Exception as exc:
            log.warning(f"Failed to save ML model: {exc}")

    def load(self) -> bool:
        path = PATHS["ml_model"]
        if not Path(path).exists():
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            with self._lock:
                self.model = data["model"]
                self.feature_cols = data.get("feature_cols", self.cfg.ml_features)
                self.oos_accuracy = data.get("oos_acc", 0.0)
            log.info(f"ML model loaded (OOS acc={self.oos_accuracy:.3f}).")
            return True
        except Exception as exc:
            log.warning(f"Failed to load ML model: {exc}")
            return False


# ---------------------------------------------------------------------------
# Pairs trading / cointegration
# ---------------------------------------------------------------------------


class PairsSignalModel:
    """
    Simple Engle-Granger cointegration check for all symbol pairs.
    Generates mean-reversion signals when spread deviates > Z threshold.
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        # {(sym1, sym2): {"pvalue": float, "half_life": float, "spread_mean": float, "spread_std": float}}
        self._pairs: Dict[Tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def update_cointegration(self, price_series: Dict[str, pd.Series]) -> None:
        """
        Compute cointegration for all pairs.  Expensive – run in background thread.
        price_series: {symbol: Series of closing prices}
        """
        if not _HAS_STATSMODELS:
            return

        symbols = list(price_series.keys())
        results = {}

        for i, s1 in enumerate(symbols):
            for s2 in symbols[i + 1 :]:
                p1 = price_series[s1].dropna()
                p2 = price_series[s2].dropna()
                # Align
                p1, p2 = p1.align(p2, join="inner")
                if len(p1) < 60:
                    continue
                try:
                    _, pvalue, _ = coint(p1.values, p2.values)
                except Exception:
                    continue

                if pvalue > self.cfg.pairs_min_coint_pvalue:
                    continue

                spread = (p1 - p2).values
                spread_mean = float(np.mean(spread))
                spread_std = float(np.std(spread))
                # Half-life of mean reversion via AR(1)
                lag_spread = spread[:-1]
                diff_spread = np.diff(spread)
                if len(lag_spread) < 10:
                    continue
                try:
                    beta = np.polyfit(lag_spread, diff_spread, 1)[0]
                    half_life = max(1.0, -np.log(2) / beta) if beta < 0 else 0.0
                except Exception:
                    half_life = 0.0

                if half_life <= 0 or half_life > 200:
                    continue

                results[(s1, s2)] = {
                    "pvalue": float(pvalue),
                    "half_life": half_life,
                    "spread_mean": spread_mean,
                    "spread_std": spread_std,
                }

        with self._lock:
            self._pairs = results
        log.info(f"Pairs: found {len(results)} cointegrated pairs.")

    # ------------------------------------------------------------------

    def get_signal(self, sym1: str, sym2: str, price1: float, price2: float) -> Optional[float]:
        """
        Return z-score of current spread, or None if pair not cointegrated.
        Positive z → spread above mean → sell sym1 / buy sym2 (mean-reversion).
        """
        with self._lock:
            key = (sym1, sym2) if (sym1, sym2) in self._pairs else (sym2, sym1)
            pair = self._pairs.get(key)

        if pair is None:
            return None

        spread = price1 - price2
        z = (spread - pair["spread_mean"]) / max(pair["spread_std"], 1e-10)
        return float(z)

    def get_pairs(self) -> Dict[Tuple[str, str], dict]:
        with self._lock:
            return dict(self._pairs)


# ---------------------------------------------------------------------------
# Dynamic signal fusion
# ---------------------------------------------------------------------------


class SignalFusion:
    """
    Combines:
      1. Technical condition (binary gate)
      2. XGBoost ML probability
      3. Order-book imbalance score
      4. Pairs z-score (optional)

    Weights are adjusted each cycle based on recent per-model Sharpe.
    Final output: fused probability in [0, 1].
    """

    def __init__(self, cfg: AegisConfig):
        self.cfg = cfg
        # Rolling per-model PnL lists for Sharpe calculation
        self._model_pnl: Dict[str, list] = {
            "technical": [],
            "ml": [],
            "ob": [],
        }
        # Current weights (initialised equally)
        self._weights: Dict[str, float] = {
            "technical": 0.40,
            "ml": 0.45,
            "ob": 0.15,
        }
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def fuse(
        self,
        technical_signal: Optional[str],  # "TREND" | "RANGE" | "BREAKOUT" | None
        ml_prob: float,  # 0–1 from XGBoost
        ob_imbalance: float,  # bid/ask ratio
        pairs_z: Optional[float] = None,
    ) -> float:
        """
        Returns fused probability in [0, 1].
        """
        # Technical gate: convert signal type to a score
        tech_score = {
            "TREND": 0.80,
            "BREAKOUT": 0.70,
            "RANGE": 0.65,
            None: 0.00,
        }.get(technical_signal, 0.0)

        # OB imbalance → 0–1 score
        # imbalance > 2 is very bullish (bids >> asks)
        ob_score = sigmoid((ob_imbalance - 1.0) * 2.0)  # logistic centred at 1.0

        with self._lock:
            w = self._weights.copy()

        fused = w["technical"] * tech_score + w["ml"] * ml_prob + w["ob"] * ob_score

        # If pairs z-score is very negative (spread too wide, mean-rev opportunity)
        # treat it as a modest additive boost (capped)
        if pairs_z is not None and pairs_z < -self.cfg.pairs_zscore_threshold:
            fused = min(1.0, fused + 0.05)

        return float(np.clip(fused, 0.0, 1.0))

    # ------------------------------------------------------------------

    def update_weights(self) -> None:
        """
        Adjust weights proportional to each model's recent Sharpe.
        Called periodically (e.g. hourly).
        """
        with self._lock:
            sharpes = {}
            for model, pnl_list in self._model_pnl.items():
                if len(pnl_list) < 5:
                    sharpes[model] = 1.0  # default equal weight
                    continue
                arr = np.array(pnl_list[-50:])  # last 50 trades
                mean_r = np.mean(arr)
                std_r = np.std(arr)
                sharpes[model] = safe_div(mean_r, std_r, default=0.0)

            # Shift all sharpes to be positive
            min_s = min(sharpes.values())
            if min_s < 0:
                sharpes = {k: v - min_s + 0.01 for k, v in sharpes.items()}

            total = sum(sharpes.values()) or 1.0
            self._weights = {k: v / total for k, v in sharpes.items()}
            log.info(f"Signal weights updated: {self._weights}")

    def record_trade_pnl(self, model_attribution: str, pnl: float) -> None:
        """Record realised PnL attributed to a model signal for Sharpe tracking."""
        with self._lock:
            lst = self._model_pnl.get(model_attribution, [])
            lst.append(pnl)
            if len(lst) > 200:
                lst.pop(0)
            self._model_pnl[model_attribution] = lst
