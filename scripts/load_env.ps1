param(
    [string]$EnvFile = ".env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (!(Test-Path $EnvFile)) {
    throw "Environment file not found: $EnvFile"
}

# ------------------------------------------------------------
# Load raw .env values into the current PowerShell process.
# ------------------------------------------------------------
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()

    if ([string]::IsNullOrWhiteSpace($line)) {
        return
    }

    if ($line.StartsWith("#")) {
        return
    }

    $separatorIndex = $line.IndexOf("=")

    if ($separatorIndex -lt 1) {
        return
    }

    $name = $line.Substring(0, $separatorIndex).Trim()
    $value = $line.Substring($separatorIndex + 1).Trim()

    if (
        ($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))
    ) {
        $value = $value.Substring(1, $value.Length - 2)
    }

    [System.Environment]::SetEnvironmentVariable(
        $name,
        $value,
        "Process"
    )
}

# ------------------------------------------------------------
# Resolve operating mode.
# Default remains PAPER for safety.
# ------------------------------------------------------------
$mode = [System.Environment]::GetEnvironmentVariable(
    "AEGIS_MODE",
    "Process"
)

if ([string]::IsNullOrWhiteSpace($mode)) {
    $mode = "PAPER"
}

$mode = $mode.Trim().ToUpperInvariant()

if ($mode -notin @("PAPER", "LIVE")) {
    throw "Invalid AEGIS_MODE '$mode'. Allowed values: PAPER or LIVE."
}

[System.Environment]::SetEnvironmentVariable(
    "AEGIS_MODE",
    $mode,
    "Process"
)

function Select-CredentialProfile {
    param(
        [string]$ExchangeName,
        [string]$Mode,
        [string]$TestnetKeyVar,
        [string]$TestnetSecretVar,
        [string]$LiveKeyVar,
        [string]$LiveSecretVar,
        [string]$RuntimeKeyVar,
        [string]$RuntimeSecretVar,
        [bool]$RequiredInLive = $false
    )

    if ($Mode -eq "PAPER") {
        $selectedKey = [System.Environment]::GetEnvironmentVariable(
            $TestnetKeyVar,
            "Process"
        )

        $selectedSecret = [System.Environment]::GetEnvironmentVariable(
            $TestnetSecretVar,
            "Process"
        )

        [System.Environment]::SetEnvironmentVariable(
            $RuntimeKeyVar,
            $selectedKey,
            "Process"
        )

        [System.Environment]::SetEnvironmentVariable(
            $RuntimeSecretVar,
            $selectedSecret,
            "Process"
        )

        if (
            [string]::IsNullOrWhiteSpace($selectedKey) -or
            [string]::IsNullOrWhiteSpace($selectedSecret)
        ) {
            Write-Host "$ExchangeName PAPER/Testnet credentials: NOT SET | public market-data only."
        }
        else {
            Write-Host "$ExchangeName PAPER/Testnet credentials selected."
        }
    }
    else {
        $selectedKey = [System.Environment]::GetEnvironmentVariable(
            $LiveKeyVar,
            "Process"
        )

        $selectedSecret = [System.Environment]::GetEnvironmentVariable(
            $LiveSecretVar,
            "Process"
        )

        if (
            $RequiredInLive -and
            (
                [string]::IsNullOrWhiteSpace($selectedKey) -or
                [string]::IsNullOrWhiteSpace($selectedSecret)
            )
        ) {
            throw "AEGIS_MODE=LIVE requires $LiveKeyVar and $LiveSecretVar."
        }

        [System.Environment]::SetEnvironmentVariable(
            $RuntimeKeyVar,
            $selectedKey,
            "Process"
        )

        [System.Environment]::SetEnvironmentVariable(
            $RuntimeSecretVar,
            $selectedSecret,
            "Process"
        )

        if (
            [string]::IsNullOrWhiteSpace($selectedKey) -or
            [string]::IsNullOrWhiteSpace($selectedSecret)
        ) {
            Write-Host "$ExchangeName LIVE credentials: NOT SET | execution disabled for this exchange."
        }
        else {
            Write-Host "$ExchangeName LIVE credentials selected."
        }
    }
}

Select-CredentialProfile `
    -ExchangeName "Binance" `
    -Mode $mode `
    -TestnetKeyVar "BINANCE_TESTNET_API_KEY" `
    -TestnetSecretVar "BINANCE_TESTNET_SECRET" `
    -LiveKeyVar "BINANCE_LIVE_API_KEY" `
    -LiveSecretVar "BINANCE_LIVE_SECRET" `
    -RuntimeKeyVar "BINANCE_API_KEY" `
    -RuntimeSecretVar "BINANCE_SECRET" `
    -RequiredInLive $true

Select-CredentialProfile `
    -ExchangeName "Bybit" `
    -Mode $mode `
    -TestnetKeyVar "BYBIT_TESTNET_API_KEY" `
    -TestnetSecretVar "BYBIT_TESTNET_SECRET" `
    -LiveKeyVar "BYBIT_LIVE_API_KEY" `
    -LiveSecretVar "BYBIT_LIVE_SECRET" `
    -RuntimeKeyVar "BYBIT_API_KEY" `
    -RuntimeSecretVar "BYBIT_SECRET" `
    -RequiredInLive $false


Select-CredentialProfile `
    -ExchangeName "OKX" `
    -Mode $mode `
    -TestnetKeyVar "OKX_TESTNET_API_KEY" `
    -TestnetSecretVar "OKX_TESTNET_SECRET" `
    -LiveKeyVar "OKX_LIVE_API_KEY" `
    -LiveSecretVar "OKX_LIVE_SECRET" `
    -RuntimeKeyVar "OKX_API_KEY" `
    -RuntimeSecretVar "OKX_SECRET" `
    -RequiredInLive $false

if ($mode -eq "PAPER") {
    $okxPassphrase = [System.Environment]::GetEnvironmentVariable("OKX_TESTNET_PASSPHRASE", "Process")

    if ([string]::IsNullOrWhiteSpace($okxPassphrase)) {
        $okxPassphrase = [System.Environment]::GetEnvironmentVariable("OKX_TESTNET_PASSWORD", "Process")
    }
}
else {
    $okxPassphrase = [System.Environment]::GetEnvironmentVariable("OKX_LIVE_PASSPHRASE", "Process")

    if ([string]::IsNullOrWhiteSpace($okxPassphrase)) {
        $okxPassphrase = [System.Environment]::GetEnvironmentVariable("OKX_LIVE_PASSWORD", "Process")
    }
}

[System.Environment]::SetEnvironmentVariable("OKX_PASSPHRASE", $okxPassphrase, "Process")
[System.Environment]::SetEnvironmentVariable("OKX_PASSWORD", $okxPassphrase, "Process")

if (
    [string]::IsNullOrWhiteSpace([System.Environment]::GetEnvironmentVariable("OKX_API_KEY", "Process")) -or
    [string]::IsNullOrWhiteSpace([System.Environment]::GetEnvironmentVariable("OKX_SECRET", "Process")) -or
    [string]::IsNullOrWhiteSpace([System.Environment]::GetEnvironmentVariable("OKX_PASSPHRASE", "Process"))
) {
    Write-Host "OKX credentials: NOT SET | market-data only."
}
else {
    Write-Host "OKX credentials selected."
}

Write-Host "Loaded $EnvFile | MODE=$mode"
