#!/usr/bin/env bash
set -euo pipefail

ENGINE_PATH="${1:-/workspace/deepstream_coursework/models/yolo/best.onnx_b1_gpu0_fp16.engine}"

/usr/src/tensorrt/bin/trtexec \
  --onnx=/workspace/deepstream_coursework/models/yolo/best.onnx \
  --saveEngine="$ENGINE_PATH" \
  --fp16 \
  --memPoolSize=workspace:6144
