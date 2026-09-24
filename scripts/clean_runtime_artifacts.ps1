Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "Removing Python cache folders..."

Get-ChildItem -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Removing .pytest_cache..."

if (Test-Path ".pytest_cache") {
    Remove-Item ".pytest_cache" -Recurse -Force
}

Write-Host "Moving old one-off maintenance scripts if present..."

$maintenanceDir = "scripts\maintenance"

if (!(Test-Path $maintenanceDir)) {
    New-Item -ItemType Directory -Path $maintenanceDir | Out-Null
}

$movable = @(
    "fix_encoding.ps1",
    "get-pip.py"
)

foreach ($file in $movable) {
    if (Test-Path $file) {
        Move-Item $file (Join-Path $maintenanceDir $file) -Force
        Write-Host "Moved $file to $maintenanceDir"
    }
}

Write-Host "Runtime artifact cleanup completed."