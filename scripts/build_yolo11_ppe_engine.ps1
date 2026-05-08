param(
    [string]$Image = "ghcr.io/insight-platform/savant-deepstream:latest",
    [string]$EnginePath = "models/yolo/best.onnx_b1_gpu0_fp16.engine"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

docker run --rm --gpus all `
    -e NVIDIA_DRIVER_CAPABILITIES=all `
    -v "${ProjectRoot}:/workspace/deepstream_coursework" `
    $Image `
    bash scripts/build_yolo11_ppe_engine.sh "/workspace/deepstream_coursework/${EnginePath}"
