param(
    [string]$EnvFile = ".env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not $env:VIRTUAL_ENV) {
    throw "Virtual environment is not active. Activate .venv before starting AEGIS."
}

Write-Host ""
Write-Host "========================================"
Write-Host "Starting AEGIS through main.py"
Write-Host "========================================"

python main.py --env-file $EnvFile run
