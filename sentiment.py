"""
sentiment.py  -  AEGIS PRO v2
External sentiment and on-chain data sources for the feature engine.

Sources (all free, no API key required unless noted):
  1. Fear & Greed Index  - alternative.me/crypto
  2. Bitcoin on-chain metrics (Blockchain.info) - NVT ratio, tx count
  3. BTC dominance & global market cap  - CoinGecko public API
  4. Funding rates  - Binance public endpoint (no key needed)

All fetches are cached with TTL and fail silently to NaN.
"""

import logging
import threading
import time
from typing import Dict, Optional

import requests

log = logging.getLogger("aegis.sentiment")

_session = requests.Session()
_session.headers.update({"User-Agent": "AegisPro/2.0"})


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------


class _TTLCache:
    def __init__(self):
        self._store: Dict[str, tuple] = {}  # key -> (value, expiry)
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            item = self._store.get(key)
            if item and time.time() < item[1]:
                return item[0]
        return None

    def set(self, key: str, value, ttl: float) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + ttl)


_cache = _TTLCache()


def _safe_get(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.debug(f"Sentiment fetch failed ({url}): {exc}")
        return None


# ---------------------------------------------------------------------------
# Fear & Greed Index
# ---------------------------------------------------------------------------

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1&format=json"
FEAR_GREED_TTL = 3600  # update hourly


def get_fear_greed() -> float:
    """
    Returns current Fear & Greed Index (0-100).
    0 = extreme fear, 100 = extreme greed.
    Returns 50.0 (neutral) on failure.
    """
    cached = _cache.get("fear_greed")
    if cached is not None:
        return cached

    data = _safe_get(FEAR_GREED_URL)
    if data and data.get("data"):
        val = float(data["data"][0].get("value", 50))
        _cache.set("fear_greed", val, FEAR_GREED_TTL)
        return val
    return 50.0


def fear_greed_normalised() -> float:
    """Returns Fear & Greed normalised to [-1, +1]. +1 = extreme greed."""
    return (get_fear_greed() - 50.0) / 50.0


# ---------------------------------------------------------------------------
# Bitcoin dominance & global market cap (CoinGecko)
# ---------------------------------------------------------------------------

COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
COINGECKO_TTL = 600  # 10 min


def get_btc_dominance() -> float:
    """Returns BTC market cap dominance as a fraction (0-1). Default 0.5."""
    cached = _cache.get("btc_dominance")
    if cached is not None:
        return cached

    data = _safe_get(COINGECKO_GLOBAL_URL)
    if data and data.get("data"):
        dom = float(data["data"].get("market_cap_percentage", {}).get("btc", 50)) / 100.0
        _cache.set("btc_dominance", dom, COINGECKO_TTL)
        return dom
    return 0.5


def get_total_market_cap_change_24h() -> float:
    """Returns 24h global crypto market cap change %. Default 0.0."""
    cached = _cache.get("mktcap_change")
    if cached is not None:
        return cached

    data = _safe_get(COINGECKO_GLOBAL_URL)
    if data and data.get("data"):
        pct = float(data["data"].get("market_cap_change_percentage_24h_usd", 0))
        _cache.set("mktcap_change", pct, COINGECKO_TTL)
        return pct
    return 0.0


# ---------------------------------------------------------------------------
# Funding rates (Binance perpetual - used as sentiment proxy for spot)
# ---------------------------------------------------------------------------

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1"
FUNDING_TTL = 3600  # funding updates every 8h; cache 1h


def get_funding_rate(symbol: str = "BTCUSDT") -> float:
    """
    Returns latest perpetual funding rate for symbol.
    Positive = longs pay shorts (bullish excess), negative = shorts pay longs.
    Returns 0.0 on failure.
    """
    key = f"funding_{symbol}"
    cached = _cache.get(key)
    if cached is not None:
        return cached

    url = BINANCE_FUNDING_URL.format(symbol=symbol.replace("/", ""))
    data = _safe_get(url)
    if data and isinstance(data, list) and data:
        rate = float(data[0].get("fundingRate", 0))
        _cache.set(key, rate, FUNDING_TTL)
        return rate
    return 0.0


# ---------------------------------------------------------------------------
# On-chain Bitcoin metrics (Blockchain.info)
# ---------------------------------------------------------------------------

BLOCKCHAIN_STATS_URL = "https://api.blockchain.info/stats"
ONCHAIN_TTL = 3600


def _get_blockchain_stats() -> Optional[dict]:
    cached = _cache.get("blockchain_stats")
    if cached is not None:
        return cached
    data = _safe_get(BLOCKCHAIN_STATS_URL)
    if data:
        _cache.set("blockchain_stats", data, ONCHAIN_TTL)
    return data


def get_btc_tx_count_24h() -> float:
    """Returns 24h Bitcoin transaction count. Normalised ~200k typical."""
    stats = _get_blockchain_stats()
    if stats:
        return float(stats.get("n_tx", 0))
    return 0.0


def get_btc_hash_rate() -> float:
    """Returns current network hash rate (TH/s). Higher = more security/confidence."""
    stats = _get_blockchain_stats()
    if stats:
        return float(stats.get("hash_rate", 0))
    return 0.0


def get_nvt_ratio_proxy() -> float:
    """
    Simplified NVT proxy: market_cap / tx_volume.
    High NVT = overvalued relative to on-chain activity.
    Returns 0 on failure.
    """
    stats = _get_blockchain_stats()
    if not stats:
        return 0.0
    tx_vol = float(stats.get("total_fees_btc", 0)) + float(stats.get("n_tx", 1))
    mkt_size = float(stats.get("market_cap_usd", 0))
    return mkt_size / max(tx_vol, 1.0)


# ---------------------------------------------------------------------------
# Aggregated sentiment feature vector
# ---------------------------------------------------------------------------


def get_sentiment_features(symbol: str = "BTC/USDT") -> Dict[str, float]:
    """
    Returns a dict of all sentiment/on-chain features for the given symbol.
    All values are floats.  Missing data returns neutral defaults.

    Called by FeatureEngine._add_sentiment() for the feature pipeline.
    """
    binance_sym = symbol.replace("/", "")

    return {
        # Macro sentiment
        "fear_greed": get_fear_greed() / 100.0,  # 0-1
        "fear_greed_norm": fear_greed_normalised(),  # -1 to +1
        "btc_dominance": get_btc_dominance(),  # 0-1
        "mktcap_change_24h": get_total_market_cap_change_24h() / 100.0,
        # Derivatives sentiment (perp funding as proxy even for spot)
        "funding_rate_btc": get_funding_rate("BTCUSDT"),
        "funding_rate_sym": get_funding_rate(binance_sym) if "BTC" not in symbol else 0.0,
        # On-chain (BTC only; used as macro signal for all symbols)
        "btc_tx_count_norm": min(get_btc_tx_count_24h() / 300_000.0, 2.0),
        "btc_hash_rate_norm": min(get_btc_hash_rate() / 600_000.0, 2.0),
        "nvt_proxy_norm": min(get_nvt_ratio_proxy() / 1e12, 2.0),
    }
