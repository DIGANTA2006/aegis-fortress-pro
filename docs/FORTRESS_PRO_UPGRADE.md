# AEGIS Fortress Pro Upgrade

This package uses the stronger AEGIS v2 codebase as the base and integrates the useful part of the small `Aegis_Fortress` bot: a 15-minute support-reclaim / trap-reversal scanner.

## What was fixed

- Replaced the unsafe small Fortress loop with the production AEGIS runtime.
- Added faster concurrent polling through `AEGIS_MARKET_FETCH_CONCURRENCY`.
- Added optional Binance + Bybit market data through `AEGIS_ENABLED_EXCHANGES=binance,bybit`.
- Added `MomentumTrapService`, which scans 15m OHLCV candles for:
  - support break and reclaim,
  - volume spike,
  - lower-wick rejection,
  - EMA 7/25 bullish confirmation,
  - MACD confirmation,
  - RSI not overextended,
  - Bollinger upper-band overextension filter.
- Kept automatic exits through the existing live strategy: take-profit, stop-loss, time stop, cooldown, and BTC market filter.
- Added `AEGIS_SYMBOL_BLOCKLIST`, useful for blocking coins with unlock/news risk such as `RESOLV/USDT` until the event passes.
- Added unit tests for the new trap analyzer.

## Why the original Aegis_Fortress was not safe enough

The uploaded `Aegis_Fortress` package had these problems:

- `main.py` had an incomplete database-signal branch; DB targets were found but not executed.
- The scan loop had no normal delay after each cycle, creating rate-limit and CPU risk.
- The simple script mixed signal detection, execution, risk, and DB status in one file.
- The standalone DB schema and order logging were inconsistent in places.
- It had no portfolio-level heat, drawdown guard, event bus, health endpoint, or production test suite.

## Recommended first run

Use PAPER first.

```powershell
cd "PATH\TO\aegis"
powershell -ExecutionPolicy Bypass -File .\RUN_AEGIS_FORTRESS_PRO.ps1
```

Then open:

```text
http://127.0.0.1:8080/health
```

## Low-capital settings

The included config is designed for roughly 12-15 USDT, not for guaranteed profit. Small accounts are hard because exchange minimum order size, taker fees, slippage, and spread can consume the edge.

Copy this file:

```powershell
Copy-Item .\configs\fortress_low_capital.env.template .\.env
```

Then edit `.env`.

## Live mode checklist

Before live mode:

1. Run paper/testnet for multiple days.
2. Confirm health endpoint shows ticks, orderbooks, and no strategy errors.
3. Use API keys with spot trading only.
4. Disable withdrawal permission on API keys.
5. Start with `AEGIS_MAX_ORDER_NOTIONAL` small.
6. Keep `AEGIS_SYMBOL_BLOCKLIST` for coins with imminent unlock/news risk.
7. Set `AEGIS_MODE=LIVE` and `AEGIS_LIVE_CONFIRM=YES_I_ACCEPT_THE_RISK` only when ready.

## RESOLV note from your Binance AI report

Your report said RESOLV had short-term technical strength but also an upcoming 1.82% unlock on 2026-06-27. That is event risk, so the default template blocks `RESOLV/USDT`. Remove it from `AEGIS_SYMBOL_BLOCKLIST` only if you intentionally accept that risk and the pair exists on your selected exchange.

## Commands

Compile all Python files:

```powershell
python main.py compile
```

Run tests:

```powershell
python -m pytest -q
```

Run bot:

```powershell
python main.py --env-file .env run
```

Check runtime:

```powershell
python main.py verify
```
