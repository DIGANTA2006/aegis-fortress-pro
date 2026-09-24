Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not $env:VIRTUAL_ENV) {
    throw "Virtual environment is not active."
}

$lines = python -m pip freeze | Sort-Object

[System.IO.File]::WriteAllLines(
    "requirements.lock.txt",
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)

$hash = Get-FileHash "requirements.lock.txt" -Algorithm SHA256

$hashContent = @"
SHA256  requirements.lock.txt
$($hash.Hash)
"@

[System.IO.File]::WriteAllText(
    "requirements.lock.sha256",
    $hashContent,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Created requirements.lock.txt"
Write-Host "Created requirements.lock.sha256"