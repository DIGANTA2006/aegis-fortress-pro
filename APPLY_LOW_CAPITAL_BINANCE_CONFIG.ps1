param(
    [string]$EnvFile = ".env",
    [switch]$Live
)

$ErrorActionPreference = "Stop"

function Set-EnvLine {
    param(
        [string[]]$Lines,
        [string]$Key,
        [string]$Value
    )

    $escapedKey = [regex]::Escape($Key)
    $line = "$Key=$Value"
    $found = $false
    $result = foreach ($existing in $Lines) {
        if ($existing -match "^\s*$escapedKey\s*=") {
            $found = $true
            $line
        } else {
            $existing
        }
    }

    if (-not $found) {
        $result += $line
    }

    return $result
}

if (-not (Test-Path $EnvFile)) {
    if (Test-Path ".env.low_capital.template") {
        Copy-Item ".env.low_capital.template" $EnvFile
    } else {
        New-Item -Path $EnvFile -ItemType File | Out-Null
    }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "$EnvFile.backup_low_capital_$stamp"
Copy-Item $EnvFile $backup -Force

$lines = Get-Content $EnvFile

$mode = "PAPER"
$confirm = ""
if ($Live) {
    $mode = "LIVE"
    $confirm = "YES_I_ACCEPT_THE_RISK"
}

$settings = [ordered]@{
    "AEGIS_MODE" = $mode
    "AEGIS_LIVE_CONFIRM" = $confirm
    "AEGIS_REFERENCE_EQUITY" = "12"
    "AEGIS_MAX_GROSS_EXPOSURE" = "7"
    "AEGIS_MAX_NET_EXPOSURE" = "7"
    "AEGIS_MAX_SYMBOL_WEIGHT" = "1.00"
    "AEGIS_MAX_ORDER_NOTIONAL" = "7"
    "AEGIS_MAX_DAILY_LOSS" = "0.30"
    "AEGIS_MAX_DRAWDOWN_PCT" = "4"
    "AEGIS_AUTO_SYMBOL_DISCOVERY" = "true"
    "AEGIS_SYMBOL_DISCOVERY_QUOTE" = "USDT"
    "AEGIS_SYMBOL_DISCOVERY_MAX_SYMBOLS" = "5"
    "AEGIS_SYMBOL_DISCOVERY_MIN_QUOTE_VOLUME" = "1000000"
    "AEGIS_SYMBOL_DISCOVERY_MIN_CHANGE_PCT" = "0"
    "AEGIS_SYMBOL_DISCOVERY_MAX_CHANGE_PCT" = "18"
    "AEGIS_SYMBOL_DISCOVERY_MAX_SPREAD_BPS" = "20"
    "AEGIS_SYMBOL_DISCOVERY_REFRESH_SECONDS" = "1800"
    "AEGIS_SYMBOL_DISCOVERY_EXCLUDED_SYMBOLS" = "USDC/USDT,FDUSD/USDT,TUSD/USDT,BUSD/USDT,DAI/USDT"
    "AEGIS_MARKET_SYMBOLS" = "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT,DOGE/USDT"
    "AEGIS_MARKET_POLL_INTERVAL_SECONDS" = "3"
    "AEGIS_ORDERBOOK_DEPTH" = "20"
    "AEGIS_MARKET_STALE_AFTER_SECONDS" = "30"
    "AEGIS_LIVE_STRATEGY_ENABLED" = "true"
    "AEGIS_STRATEGY_TARGET_NOTIONAL" = "6"
    "AEGIS_STRATEGY_MIN_ORDER_NOTIONAL" = "5.5"
    "AEGIS_STRATEGY_MAX_POSITION_NOTIONAL" = "6.8"
    "AEGIS_STRATEGY_ROLLING_WINDOW" = "30"
    "AEGIS_STRATEGY_MIN_OBSERVATIONS" = "20"
    "AEGIS_STRATEGY_ENTRY_ZSCORE" = "0.85"
    "AEGIS_STRATEGY_EXIT_ZSCORE" = "0.20"
    "AEGIS_STRATEGY_IMBALANCE_THRESHOLD" = "0.10"
    "AEGIS_STRATEGY_MAX_SPREAD_BPS" = "20"
    "AEGIS_STRATEGY_COOLDOWN_SECONDS" = "30"
    "AEGIS_STRATEGY_ORDER_TYPE" = "MARKET"
    "AEGIS_STRATEGY_TAKE_PROFIT_BPS" = "60"
    "AEGIS_STRATEGY_STOP_LOSS_BPS" = "35"
    "AEGIS_STRATEGY_MIN_PROFIT_AFTER_FEE_BPS" = "18"
    "AEGIS_STRATEGY_MAX_HOLD_SECONDS" = "900"
    "AEGIS_STRATEGY_SYMBOL_COOLDOWN_AFTER_EXIT_SECONDS" = "900"
    "AEGIS_STRATEGY_LOSS_COOLDOWN_SECONDS" = "3600"
    "AEGIS_STRATEGY_BAD_SYMBOL_DROP_BPS" = "1200"
    "AEGIS_ALLOW_SHORT_ENTRIES" = "false"
    "AEGIS_DATABASE_PATH" = "data/aegis_low_capital.db"
    "AEGIS_PORTFOLIO_STATE_PATH" = "data/portfolio_state_low_capital.json"
    "AEGIS_LOG_LEVEL" = "INFO"
    "AEGIS_METRICS_PORT" = "9000"
    "AEGIS_MONITORING_INTERVAL_SECONDS" = "5"
    "AEGIS_HEALTH_HOST" = "127.0.0.1"
    "AEGIS_HEALTH_PORT" = "8080"
    "AEGIS_HEALTH_SNAPSHOT_INTERVAL_SECONDS" = "30"
    "AEGIS_ENABLED_EXCHANGES" = "binance"
    "AEGIS_EXECUTION_EXCHANGES" = "binance"
}

foreach ($key in $settings.Keys) {
    $lines = Set-EnvLine -Lines $lines -Key $key -Value $settings[$key]
}

Set-Content -Path $EnvFile -Value $lines -Encoding UTF8

Write-Host "Updated $EnvFile with low-capital Binance settings. Backup: $backup"
if ($Live) {
    Write-Host "LIVE mode enabled. Confirm your Binance API key has only Spot trading permission and no withdrawal permission."
} else {
    Write-Host "PAPER mode enabled. Test this first before using real funds."
}
