param(
    [string]$HealthHost = "127.0.0.1",
    [int]$HealthPort = 8080,
    [int]$MetricsPort = 9000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python main.py verify --host $HealthHost --health-port $HealthPort --metrics-port $MetricsPort

if ($LASTEXITCODE -ne 0) {
    throw "Runtime endpoint verification failed."
}
