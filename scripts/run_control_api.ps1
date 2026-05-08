param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

docker compose -f docker-compose.kafka.yml up -d
docker compose -f docker-compose.zlm.yml up -d

if ($Build) {
    docker compose -f docker-compose.control.yml build
}

docker compose -f docker-compose.control.yml up -d

Write-Host "Control API: http://127.0.0.1:18080"
Write-Host "Health:      http://127.0.0.1:18080/health"
