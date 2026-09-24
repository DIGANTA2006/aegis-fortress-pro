$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Resolve-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py"
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    throw "Python not found. Install Python 3.10 or newer first."
}

$Python = Resolve-Python

if (!(Test-Path ".\.venv")) {
    Write-Host "[AEGIS] Creating virtual environment..."
    if ($Python -eq "py") {
        & py -3.10 -m venv .venv
        if ($LASTEXITCODE -ne 0) { & py -3 -m venv .venv }
    } else {
        & python -m venv .venv
    }
}

$VenvPython = ".\.venv\Scripts\python.exe"

Write-Host "[AEGIS] Installing dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt

if (!(Test-Path ".\.env")) {
    Copy-Item ".\configs\fortress_low_capital.env.template" ".\.env"
    Write-Host "[AEGIS] Created .env from configs\fortress_low_capital.env.template"
    Write-Host "[AEGIS] Open .env and add API keys before live/testnet trading. Running checks now."
}

Write-Host "[AEGIS] Running compile + tests..."
& $VenvPython main.py compile
& $VenvPython -m pytest -q

Write-Host "[AEGIS] Running live safety guard..."
& $VenvPython scripts/live_safety_check.py --env-file .env

Write-Host "[AEGIS] Starting runtime. Health: http://127.0.0.1:8080/health"
& $VenvPython main.py --env-file .env run
