Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (!(Test-Path ".\.venv\Scripts\Activate.ps1")) {
    throw ".venv not found. Create/restore your virtual environment first."
}

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
. ".\.venv\Scripts\Activate.ps1"

python main.py run
