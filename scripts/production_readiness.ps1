param(
    [string]$EnvFile = ".env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not $env:VIRTUAL_ENV) {
    throw "Virtual environment is not active."
}

python main.py --env-file $EnvFile readiness

if ($LASTEXITCODE -ne 0) {
    throw "AEGIS readiness failed."
}
