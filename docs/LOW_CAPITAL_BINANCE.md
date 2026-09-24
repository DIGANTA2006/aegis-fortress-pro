# Low-capital Binance mode

This patch is designed for very small spot accounts such as roughly ₹1000 / 10-15 USDT. It does not guarantee profit. It fixes practical bot problems that usually break small live accounts:

- one fixed symbol only (`DOGE/USDT`) replaced by optional auto symbol discovery
- order size below exchange minimum replaced by configurable minimum notional sizing
- Binance amount/price precision is applied before submission
- exit logic is no longer blocked by entry cooldown
- take-profit, stop-loss, time-stop, and symbol cooldown recycling were added
- recently bad symbols can be blocked before new entries

## Recommended first run

```powershell
cd "E:\MY PROJECT FOLDER\TRADING BOT PROJECT\aegis_v2"
.\APPLY_LOW_CAPITAL_BINANCE_CONFIG.ps1
. .\scripts\load_env.ps1 -EnvFile .env
python -m pytest tests/unit/test_live_strategy.py tests/unit/test_pre_trade_risk.py tests/unit/test_low_capital_recycling.py tests/unit/test_symbol_discovery.py -q
python runtime_main.py
```

The script defaults to `AEGIS_MODE=PAPER`.

## Live canary only after paper testing

```powershell
.\APPLY_LOW_CAPITAL_BINANCE_CONFIG.ps1 -Live
. .\scripts\load_env.ps1 -EnvFile .env
python runtime_main.py
```

For live use, keep the Binance API key restricted to Spot trading only. Do not enable withdrawal permission.

## Main knobs

- `AEGIS_AUTO_SYMBOL_DISCOVERY=true`: scans USDT spot markets and chooses candidates by liquidity, positive/neutral 24h movement, and spread.
- `AEGIS_SYMBOL_DISCOVERY_MAX_SYMBOLS=5`: keeps the watchlist small so a low-balance bot does not overtrade.
- `AEGIS_SYMBOL_DISCOVERY_REFRESH_SECONDS=1800`: refreshes the selected coin universe every 30 minutes while running.
- `AEGIS_STRATEGY_TARGET_NOTIONAL=6`: per-order target, high enough for many Binance spot minimums.
- `AEGIS_STRATEGY_MIN_ORDER_NOTIONAL=5.5`: rejects/avoids too-small orders before Binance rejects them.
- `AEGIS_STRATEGY_TAKE_PROFIT_BPS=60`: about 0.60% gross profit target.
- `AEGIS_STRATEGY_STOP_LOSS_BPS=35`: about 0.35% gross loss cut.
- `AEGIS_STRATEGY_SYMBOL_COOLDOWN_AFTER_EXIT_SECONDS=900`: after taking profit, the bot avoids immediately re-buying the same coin.
- `AEGIS_STRATEGY_LOSS_COOLDOWN_SECONDS=3600`: after stop-loss or bad trend, the bot blocks that coin longer.

## Important limitation

Auto discovery does not know the future. It only selects currently liquid, low-spread, positive/neutral-momentum symbols. Profit still depends on market movement, fees, slippage, and execution.
