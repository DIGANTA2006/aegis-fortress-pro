"""Adaptive USDT symbol discovery for low-capital spot trading.

This module ranks symbols by liquidity, spread quality, and recent momentum.
It does not predict profit; it only selects markets that are currently more
tradeable than a fixed one-coin watchlist.
"""

from __future__ import annotations

import logging
import os
import math
from dataclasses import dataclass
from typing import Iterable


log = logging.getLogger(__name__)


DEFAULT_EXCLUDED_SYMBOLS = {
    "USDC/USDT",
    "FDUSD/USDT",
    "TUSD/USDT",
    "BUSD/USDT",
    "DAI/USDT",
    "USDP/USDT",
    "EUR/USDT",
    "TRY/USDT",
    "BRL/USDT",
}

_LEVERAGED_TOKEN_MARKERS = (
    "UP/USDT",
    "DOWN/USDT",
    "BULL/USDT",
    "BEAR/USDT",
    "3L/USDT",
    "3S/USDT",
    "5L/USDT",
    "5S/USDT",
)


@dataclass(frozen=True)
class SymbolCandidate:
    symbol: str
    score: float
    quote_volume: float
    change_pct: float
    spread_bps: float


def discover_tradeable_symbols(
    exchange_manager,
    *,
    quote: str = "USDT",
    max_symbols: int = 6,
    min_quote_volume: float = 1_000_000.0,
    min_change_pct: float = 0.0,
    max_change_pct: float = 18.0,
    max_spread_bps: float = 20.0,
    excluded_symbols: Iterable[str] | None = None,
    fallback_symbols: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return a ranked symbol list from the primary exchange.

    The selector is intentionally conservative for small accounts:
    - USDT spot pairs only
    - excludes stablecoin and leveraged-token pairs
    - requires positive/neutral daily momentum by default
    - rejects high-spread markets
    - ranks by quote volume, moderate momentum, and tight spread
    """

    if max_symbols <= 0:
        return tuple(fallback_symbols)

    exchange = getattr(exchange_manager, "primary", None)

    if exchange is None:
        return tuple(fallback_symbols)

    raw_exchange = getattr(exchange, "_ex", exchange)
    markets = _safe_markets(raw_exchange)
    excluded = {
        str(item).strip().upper()
        for item in (excluded_symbols or DEFAULT_EXCLUDED_SYMBOLS)
        if str(item).strip()
    }

    symbols = [
        symbol
        for symbol, market in markets.items()
        if _is_allowed_symbol(symbol, market, quote=quote, excluded=excluded)
    ]

    if not symbols:
        log.warning("Symbol discovery found no markets; using fallback symbols")
        return tuple(fallback_symbols)

    tickers = _safe_fetch_tickers(raw_exchange, symbols)
    candidates: list[SymbolCandidate] = []

    for symbol in symbols:
        ticker = tickers.get(symbol)

        if not isinstance(ticker, dict):
            continue

        candidate = _candidate_from_ticker(symbol, ticker)

        if candidate is None:
            continue

        if candidate.quote_volume < min_quote_volume:
            continue

        if candidate.change_pct < min_change_pct:
            continue

        if candidate.change_pct > max_change_pct:
            # Very high one-day moves are often late, whippy entries for small accounts.
            continue

        if candidate.spread_bps > max_spread_bps:
            continue

        candidates.append(candidate)

    candidates.sort(key=lambda item: item.score, reverse=True)
    selected = tuple(item.symbol for item in candidates[:max_symbols])

    always_include = tuple(
        item.strip().upper()
        for item in os.getenv("AEGIS_SYMBOL_DISCOVERY_ALWAYS_INCLUDE", "").split(",")
        if item.strip()
    )

    if always_include:
        available = {symbol.upper(): symbol for symbol in markets.keys()}
        selected_list = list(selected)
        selected_upper = {symbol.upper() for symbol in selected_list}

        for requested in always_include:
            actual = available.get(requested, requested)
            if requested not in selected_upper and actual in markets:
                selected_list.append(actual)
                selected_upper.add(requested)

        selected = tuple(selected_list)

    if selected:
        log.info(
            "Auto symbol discovery selected: %s",
            ", ".join(selected),
        )
        return selected

    log.warning("Symbol discovery produced no candidates; using fallback symbols")
    return tuple(fallback_symbols)


def _safe_markets(raw_exchange) -> dict:
    markets = getattr(raw_exchange, "markets", None)

    if isinstance(markets, dict) and markets:
        return markets

    try:
        loaded = raw_exchange.load_markets()
        if isinstance(loaded, dict):
            return loaded
    except Exception as exc:
        log.warning("Symbol discovery could not load markets: %s", exc)

    return {}


def _safe_fetch_tickers(raw_exchange, symbols: list[str]) -> dict[str, dict]:
    fetch_tickers = getattr(raw_exchange, "fetch_tickers", None)

    if callable(fetch_tickers):
        try:
            payload = fetch_tickers(symbols)
            if isinstance(payload, dict):
                return payload
        except TypeError:
            try:
                payload = fetch_tickers()
                if isinstance(payload, dict):
                    return {symbol: payload.get(symbol, {}) for symbol in symbols}
            except Exception as exc:
                log.debug("fetch_tickers fallback failed: %s", exc)
        except Exception as exc:
            log.debug("fetch_tickers failed: %s", exc)

    tickers: dict[str, dict] = {}
    fetch_ticker = getattr(raw_exchange, "fetch_ticker", None)

    if not callable(fetch_ticker):
        return tickers

    for symbol in symbols[:60]:
        try:
            payload = fetch_ticker(symbol)
            if isinstance(payload, dict):
                tickers[symbol] = payload
        except Exception as exc:
            log.debug("fetch_ticker failed for %s: %s", symbol, exc)

    return tickers


def _is_allowed_symbol(symbol: str, market: dict, *, quote: str, excluded: set[str]) -> bool:
    normalized = symbol.upper()

    if normalized in excluded:
        return False

    if not normalized.endswith(f"/{quote.upper()}"):
        return False

    if any(marker in normalized for marker in _LEVERAGED_TOKEN_MARKERS):
        return False

    if isinstance(market, dict):
        if market.get("active") is False:
            return False

        if market.get("spot") is False:
            return False

    return True


def _candidate_from_ticker(symbol: str, ticker: dict) -> SymbolCandidate | None:
    last = _safe_float(
        ticker.get("last")
        or ticker.get("close")
        or ticker.get("price")
    )
    bid = _safe_float(ticker.get("bid"))
    ask = _safe_float(ticker.get("ask"))

    if last <= 0:
        if bid > 0 and ask > 0:
            last = (bid + ask) / 2.0
        else:
            return None

    quote_volume = _safe_float(
        ticker.get("quoteVolume")
        or ticker.get("quote_volume")
    )

    if quote_volume <= 0:
        base_volume = _safe_float(
            ticker.get("baseVolume")
            or ticker.get("volume")
        )
        quote_volume = base_volume * last

    change_pct = _safe_float(
        ticker.get("percentage")
        or ticker.get("change_pct")
    )

    if change_pct == 0.0:
        open_price = _safe_float(ticker.get("open"))
        if open_price > 0:
            change_pct = ((last - open_price) / open_price) * 100.0

    spread_bps = 0.0

    if bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 10_000.0

    score = _score_candidate(
        quote_volume=quote_volume,
        change_pct=change_pct,
        spread_bps=spread_bps,
    )

    return SymbolCandidate(
        symbol=symbol,
        score=score,
        quote_volume=quote_volume,
        change_pct=change_pct,
        spread_bps=spread_bps,
    )


def _score_candidate(*, quote_volume: float, change_pct: float, spread_bps: float) -> float:
    liquidity_score = math.log10(max(quote_volume, 1.0))
    momentum_score = min(max(change_pct, -5.0), 12.0) / 3.0
    spread_penalty = max(spread_bps, 0.0) / 4.0
    pump_penalty = max(change_pct - 12.0, 0.0) / 2.0

    return liquidity_score + momentum_score - spread_penalty - pump_penalty


def _safe_float(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0

    return 0.0
