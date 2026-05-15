param(
    [string]$Python = "python",
    [int]$Task6ApiPort = 18061,
    [int]$Task9ApiPort = 18069,
    [switch]$RunTask6Worker,
    [switch]$RunTask9Worker
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "[run] workspace: $root"

Start-Process -WindowStyle Hidden -FilePath $Python -ArgumentList @("-m", "uvicorn", "region_guard.api:app", "--host", "0.0.0.0", "--port", "$Task6ApiPort")
Write-Host "[ok] RegionGuard api: http://127.0.0.1:$Task6ApiPort/api/v1/alerts"

Start-Process -WindowStyle Hidden -FilePath $Python -ArgumentList @("-m", "uvicorn", "stream_doctor.api:app", "--host", "0.0.0.0", "--port", "$Task9ApiPort")
Write-Host "[ok] StreamDoctor api: http://127.0.0.1:$Task9ApiPort/api/v1/vqd/status"

if ($RunTask6Worker) {
    Start-Process -WindowStyle Hidden -FilePath $Python -ArgumentList @("-m", "region_guard.worker")
    Write-Host "[ok] RegionGuard worker started"
}

if ($RunTask9Worker) {
    Start-Process -WindowStyle Hidden -FilePath $Python -ArgumentList @("-m", "stream_doctor.worker")
    Write-Host "[ok] StreamDoctor worker started"
}

Write-Host "[done] launched requested services"
