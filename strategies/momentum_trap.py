from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd


@dataclass(frozen=True)
class MomentumTrapConfig:
    """Parameters for the Fortress-style trap and pullback scanner."""

    support_window: int = 20
    volume_window: int = 20
    min_volume_multiplier: float = 1.5
    min_wick_body_ratio: float = 1.2
    ema_fast: int = 7
    ema_slow: int = 25
    rsi_period: int = 6
    rsi_min: float = 45.0
    rsi_max: float = 68.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_window: int = 20
    bollinger_std: float = 2.0
    pullback_tolerance_bps: float = 85.0
    min_closed_candles: int = 35


@dataclass(frozen=True)
class MomentumTrapDecision:
    symbol: str
    should_buy: bool
    reason: str
    signal_key: str | None = None
    confidence: float = 0.0
    reference_price: float = 0.0
    metrics: dict[str, float | bool | str] = field(default_factory=dict)


class MomentumTrapAnalyzer:
    """
    Pure OHLCV analyzer used by the runtime service.

    It intentionally uses the latest *completed* candle (index -2) instead of
    the actively forming candle to reduce repaint/noise in live trading.
    """

    def __init__(self, config: MomentumTrapConfig | None = None) -> None:
        self.config = config or MomentumTrapConfig()

    def analyze(self, symbol: str, ohlcv: Sequence[Sequence[Any]]) -> MomentumTrapDecision:
        cfg = self.config

        if len(ohlcv) < cfg.min_closed_candles:
            return MomentumTrapDecision(
                symbol=symbol,
                should_buy=False,
                reason="not_enough_candles",
                metrics={"candles": float(len(ohlcv))},
            )

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )

        for column in ["open", "high", "low", "close", "volume"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close", "volume"])

        if len(df) < cfg.min_closed_candles:
            return MomentumTrapDecision(
                symbol=symbol,
                should_buy=False,
                reason="not_enough_valid_candles",
                metrics={"valid_candles": float(len(df))},
            )

        df["support"] = df["low"].rolling(cfg.support_window).min().shift(1)
        df["avg_volume"] = df["volume"].rolling(cfg.volume_window).mean().shift(1)
        df["ema_fast"] = df["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=cfg.ema_slow, adjust=False).mean()
        df["macd"] = df["close"].ewm(span=cfg.macd_fast, adjust=False).mean() - df["close"].ewm(
            span=cfg.macd_slow,
            adjust=False,
        ).mean()
        df["macd_signal"] = df["macd"].ewm(span=cfg.macd_signal, adjust=False).mean()
        df["bb_mid"] = df["close"].rolling(cfg.bollinger_window).mean()
        df["bb_std"] = df["close"].rolling(cfg.bollinger_window).std(ddof=0)
        df["bb_upper"] = df["bb_mid"] + (cfg.bollinger_std * df["bb_std"])

        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(cfg.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(cfg.rsi_period).mean()
        loss = loss.mask(loss == 0)
        rs = gain / loss
        df["rsi"] = (100 - (100 / (1 + rs))).astype(float).fillna(50.0)

        candle = df.iloc[-2]
        previous = df.iloc[-3]

        timestamp = int(float(candle["timestamp"])) if pd.notna(candle["timestamp"]) else 0
        signal_key = f"momentum_trap:{symbol}:{timestamp}"

        body_size = abs(float(candle["close"] - candle["open"]))
        lower_wick = float(min(candle["open"], candle["close"]) - candle["low"])
        support = float(candle["support"] or 0.0)
        avg_volume = float(candle["avg_volume"] or 0.0)
        close = float(candle["close"])
        ema_fast = float(candle["ema_fast"])
        ema_slow = float(candle["ema_slow"])
        rsi = float(candle["rsi"])
        macd = float(candle["macd"])
        macd_signal = float(candle["macd_signal"])
        bb_mid = float(candle["bb_mid"] or 0.0)
        bb_upper = float(candle["bb_upper"] or 0.0)

        support_broken = support > 0 and float(candle["low"]) < support
        support_reclaimed = support > 0 and close > support
        volume_spike = avg_volume > 0 and float(candle["volume"]) >= avg_volume * cfg.min_volume_multiplier
        wick_rejection = lower_wick > max(body_size, close * 0.0001) * cfg.min_wick_body_ratio
        ema_bullish = ema_fast > ema_slow
        macd_bullish = macd > macd_signal
        rsi_ok = cfg.rsi_min <= rsi <= cfg.rsi_max
        not_extended = bb_upper <= 0 or close <= bb_upper

        trap_core = support_broken and support_reclaimed and volume_spike and wick_rejection

        near_ema_slow = self._within_bps(close, ema_slow, cfg.pullback_tolerance_bps)
        near_bb_mid = bb_mid > 0 and self._within_bps(close, bb_mid, cfg.pullback_tolerance_bps)
        higher_close = close > float(previous["close"])
        pullback_reclaim = (near_ema_slow or near_bb_mid) and higher_close

        trend_confirmed = ema_bullish and macd_bullish and rsi_ok and not_extended
        should_buy = bool(trend_confirmed and (trap_core or pullback_reclaim))

        if should_buy:
            reason = "trap_reclaim" if trap_core else "bullish_pullback_reclaim"
        elif trap_core and not trend_confirmed:
            reason = "trap_without_trend_confirmation"
        elif not trap_core and not pullback_reclaim:
            reason = "no_entry_pattern"
        else:
            reason = "trend_filters_failed"

        confidence = 0.0
        if should_buy:
            confidence = 0.55
            if trap_core:
                confidence += 0.20
            if volume_spike:
                confidence += 0.08
            if macd_bullish:
                confidence += 0.07
            if 50.0 <= rsi <= 62.0:
                confidence += 0.05
            confidence = min(1.0, confidence)

        metrics: dict[str, float | bool | str] = {
            "close": close,
            "support": support,
            "volume": float(candle["volume"]),
            "avg_volume": avg_volume,
            "volume_spike": volume_spike,
            "lower_wick": lower_wick,
            "body_size": body_size,
            "support_broken": support_broken,
            "support_reclaimed": support_reclaimed,
            "wick_rejection": wick_rejection,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_bullish": ema_bullish,
            "rsi": rsi,
            "rsi_ok": rsi_ok,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_bullish": macd_bullish,
            "bb_mid": bb_mid,
            "bb_upper": bb_upper,
            "not_extended": not_extended,
            "trap_core": trap_core,
            "pullback_reclaim": pullback_reclaim,
        }

        return MomentumTrapDecision(
            symbol=symbol,
            should_buy=should_buy,
            reason=reason,
            signal_key=signal_key,
            confidence=confidence,
            reference_price=close,
            metrics=metrics,
        )

    @staticmethod
    def _within_bps(price: float, reference: float, tolerance_bps: float) -> bool:
        if price <= 0 or reference <= 0:
            return False

        return abs(price - reference) / reference * 10_000.0 <= tolerance_bps
