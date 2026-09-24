from pathlib import Path

env_path = Path(".env")

updates = {
    "AEGIS_MODE": "PAPER",
    "AEGIS_LIVE_CONFIRM": "",
    "AEGIS_ENABLED_EXCHANGES": "binance",
    "AEGIS_EXECUTION_EXCHANGES": "binance",

    "AEGIS_REFERENCE_EQUITY": "12",
    "AEGIS_MAX_GROSS_EXPOSURE": "7",
    "AEGIS_MAX_NET_EXPOSURE": "7",
    "AEGIS_MAX_SYMBOL_WEIGHT": "1.00",
    "AEGIS_MAX_ORDER_NOTIONAL": "7",
    "AEGIS_MAX_DAILY_LOSS": "0.25",
    "AEGIS_MAX_DRAWDOWN_PCT": "4",

    "AEGIS_AUTO_SYMBOL_DISCOVERY": "true",
    "AEGIS_SYMBOL_DISCOVERY_QUOTE": "USDT",
    "AEGIS_SYMBOL_DISCOVERY_MAX_SYMBOLS": "8",
    "AEGIS_SYMBOL_DISCOVERY_MIN_QUOTE_VOLUME": "250000",
    "AEGIS_SYMBOL_DISCOVERY_MIN_CHANGE_PCT": "-3",
    "AEGIS_SYMBOL_DISCOVERY_MAX_CHANGE_PCT": "12",
    "AEGIS_SYMBOL_DISCOVERY_MAX_SPREAD_BPS": "25",
    "AEGIS_SYMBOL_DISCOVERY_EXCLUDED_SYMBOLS": "USDC/USDT,FDUSD/USDT,TUSD/USDT,BUSD/USDT,DAI/USDT,USDP/USDT,EUR/USDT,TRY/USDT",

    "AEGIS_MARKET_SYMBOLS": "XLM/USDT,DOGE/USDT,TRX/USDT,ADA/USDT,XRP/USDT,SOL/USDT,BNB/USDT,ETH/USDT,BTC/USDT",
    "AEGIS_MARKET_POLL_INTERVAL_SECONDS": "3",
    "AEGIS_ORDERBOOK_DEPTH": "20",
    "AEGIS_MARKET_STALE_AFTER_SECONDS": "30",

    "AEGIS_LIVE_STRATEGY_ENABLED": "true",
    "AEGIS_STRATEGY_TARGET_NOTIONAL": "6",
    "AEGIS_STRATEGY_MIN_ORDER_NOTIONAL": "5.5",
    "AEGIS_STRATEGY_MAX_POSITION_NOTIONAL": "6.8",
    "AEGIS_STRATEGY_ROLLING_WINDOW": "30",
    "AEGIS_STRATEGY_MIN_OBSERVATIONS": "20",
    "AEGIS_STRATEGY_ENTRY_ZSCORE": "0.90",
    "AEGIS_STRATEGY_EXIT_ZSCORE": "0.20",
    "AEGIS_STRATEGY_IMBALANCE_THRESHOLD": "0.12",
    "AEGIS_STRATEGY_MAX_SPREAD_BPS": "22",
    "AEGIS_STRATEGY_COOLDOWN_SECONDS": "30",
    "AEGIS_STRATEGY_ORDER_TYPE": "MARKET",
    "AEGIS_ALLOW_SHORT_ENTRIES": "false",

    "AEGIS_STRATEGY_TAKE_PROFIT_BPS": "55",
    "AEGIS_STRATEGY_STOP_LOSS_BPS": "35",
    "AEGIS_STRATEGY_MIN_PROFIT_AFTER_FEE_BPS": "18",
    "AEGIS_STRATEGY_MAX_HOLD_SECONDS": "900",
    "AEGIS_STRATEGY_SYMBOL_COOLDOWN_AFTER_EXIT_SECONDS": "600",
    "AEGIS_STRATEGY_LOSS_COOLDOWN_SECONDS": "2400",
    "AEGIS_STRATEGY_BAD_SYMBOL_DROP_BPS": "900",

    "AEGIS_DATABASE_PATH": "data/aegis_low_capital.db",
    "AEGIS_PORTFOLIO_STATE_PATH": "data/portfolio_state_low_capital.json",
    "AEGIS_LOG_LEVEL": "INFO",
    "AEGIS_HEALTH_HOST": "127.0.0.1",
    "AEGIS_HEALTH_PORT": "8080",
}

lines = []
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()

seen = set()
out = []

for line in lines:
    stripped = line.strip()

    if not stripped or stripped.startswith("#") or "=" not in line:
        out.append(line)
        continue

    key = line.split("=", 1)[0].strip()

    if key in updates:
        if key not in seen:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        continue

    out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
print("Updated .env safely.")
