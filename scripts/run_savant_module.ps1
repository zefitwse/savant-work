param(
    [switch]$PullImages,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

docker compose -f docker-compose.kafka.yml up -d
docker compose -f docker-compose.control.yml up -d

if ($PullImages) {
    docker pull ghcr.io/insight-platform/savant-deepstream:latest
    docker pull ghcr.io/insight-platform/savant-adapters-gstreamer:latest
}

if ($Build) {
    docker compose -f docker-compose.savant.yml build savant-module
}

docker compose -f docker-compose.savant.yml up
