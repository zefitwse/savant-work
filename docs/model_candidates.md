# Pretrained Model Candidates

本文档记录当前可优先用于课程项目联调的预训练模型候选。

目标：

- 先用可获得的模型把 DeepStream/Kafka/ZLMediaKit/前后端链路跑通。
- 后续再替换为自己训练或更贴近现场数据的模型。
- 当前主线已经迁移到 Savant 配置，DeepStream `nvinfer` 由 Savant runtime 管理；模型候选仍按 ONNX/TensorRT 可接入性评估。

## 1. DeepStream/TAO 优先模型

这些模型来自 NVIDIA TAO/NGC，更适合先接入 DeepStream：

| Requirement | Recommended Model | Usage |
| --- | --- | --- |
| 行人检测 | PeopleNet | PGIE 或单独 person detector |
| 车辆检测 | TrafficCamNet / DashCamNet | PGIE vehicle detector |
| 车牌检测 | LPDNet | vehicle crop 上检测 license plate |
| 车牌识别 | LPRNet | license plate crop OCR |

参考：

- NVIDIA TAO Getting Started lists `PeopleNet`, `TrafficCamNet`, `LPDNet`, `LPRNet` and other purpose-built models.
- NVIDIA TAO DeepStream integration docs provide model download and `nvinfer` integration examples.

建议：

- 车牌相关优先用 NVIDIA `LPDNet + LPRNet`，因为这条路线更接近 DeepStream 原生示例。
- 安全帽/工服没有足够好用的官方 DeepStream sample，需要使用 YOLO/PPE 模型或自行训练。

## 2. YOLO Safety Helmet / PPE Candidates

### Candidate A: `iam-tsr/yolov8n-helmet-detection`

URL:

```text
https://huggingface.co/iam-tsr/yolov8n-helmet-detection
```

Files:

```text
best.pt
```

License:

```text
MIT
```

Classes:

```text
helmet
no_helmet
```

Reported metrics:

```text
Precision: 0.855
Recall: 0.808
mAP@0.5: 0.881
mAP@0.5:0.95: 0.538
```

Recommendation:

- Best first candidate for simple safety helmet demo.
- Small YOLOv8n model, easy to export to ONNX.
- Only solves helmet/no_helmet, not workwear.

Download:

```bash
python - <<'PY'
from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id="iam-tsr/yolov8n-helmet-detection",
    filename="best.pt",
    local_dir="models/yolo_helmet_iam_tsr",
)
print(path)
PY
```

Export ONNX:

```bash
pip install ultralytics huggingface_hub
yolo export model=models/yolo_helmet_iam_tsr/best.pt format=onnx imgsz=640 opset=12 simplify=True
```

### Candidate B: `Hansung-Cho/yolov8-ppe-detection`

URL:

```text
https://huggingface.co/Hansung-Cho/yolov8-ppe-detection
```

Files:

```text
best.pt
```

License:

```text
MIT
```

Classes include:

```text
Person
Hardhat
No-Hardhat
Safety Vest
No-Safety Vest
Mask
No-Mask
```

Reported metrics:

```text
mAP@0.50: 0.744
mAP@0.50:0.95: 0.436
Precision: 0.831
Recall: 0.685
```

Recommendation:

- Best candidate if we want one demo model to cover safety helmet and workwear/safety vest.
- Useful for frontend/backend alert demo because it can emit `No-Hardhat` and `No-Safety Vest`.
- Accuracy may need local validation on our own video.

Download:

```bash
python - <<'PY'
from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id="Hansung-Cho/yolov8-ppe-detection",
    filename="best.pt",
    local_dir="models/yolo_ppe_hansung",
)
print(path)
PY
```

Export ONNX:

```bash
pip install ultralytics huggingface_hub
yolo export model=models/yolo_ppe_hansung/best.pt format=onnx imgsz=640 opset=12 simplify=True
```

### Candidate C: `nduka1999/nd_ppe_yolo11s`

URL:

```text
https://huggingface.co/nduka1999/nd_ppe_yolo11s
```

Files:

```text
best.onnx
```

License:

```text
MIT
```

Classes:

```text
0 hardhat
1 no-hardhat
2 vest
3 no-vest
4 person
```

Reported metrics:

```text
Test mAP50: 93.2%
Test mAP50-95: 63.9%
```

Recommendation:

- Strong candidate because ONNX is already provided.
- Covers both safety helmet and vest/workwear-like compliance.
- It is YOLO11s, not YOLOv8, so DeepStream parser compatibility must be tested.

Download:

```bash
python - <<'PY'
from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id="nduka1999/nd_ppe_yolo11s",
    filename="best.onnx",
    local_dir="models/yolo_ppe_nduka",
)
print(path)
PY
```

### Candidate D: `keremberke/yolov8n-protective-equipment-detection`

URL:

```text
https://huggingface.co/keremberke/yolov8n-protective-equipment-detection
```

Files:

```text
best.pt
```

Classes:

```text
glove
goggles
helmet
mask
no_glove
no_goggles
no_helmet
no_mask
no_shoes
shoes
```

Reported metric:

```text
mAP@0.5: 0.247
```

Recommendation:

- Use only as backup.
- Class coverage is wide, but reported mAP is low.

### Candidate E: `sharathhhhh/safetyHelmet-detection-yolov8`

URL:

```text
https://huggingface.co/sharathhhhh/safetyHelmet-detection-yolov8
```

License:

```text
Apache-2.0
```

Classes:

```text
with_helmet
without_helmet
```

Recommendation:

- Useful as another simple helmet/no-helmet candidate.
- Check files and run local validation before DeepStream integration.

## 3. Recommended Selection

For our current coursework demo:

1. Current PGIE uses YOLO COCO ONNX for `person` / vehicle-like / foreign-object placeholder detection.
2. Current SGIE uses `nduka1999/nd_ppe_yolo11s` ONNX as `yolo_ppe_secondary`, because it already provides `hardhat/no-hardhat/vest/no-vest/person`.
3. Use `iam-tsr/yolov8n-helmet-detection` if a simpler helmet-only fallback is needed.
4. Use `Hansung-Cho/yolov8-ppe-detection` if we later want broader PPE classes.

## 4. DeepStream Integration Notes

YOLO `.pt` cannot be used directly by `nvinfer`.

Required conversion path:

```text
best.pt
  -> ONNX
  -> TensorRT engine
  -> DeepStream nvinfer config
```

Important:

- YOLO model output usually needs a custom parser in DeepStream.
- If using Ultralytics exported ONNX with NMS included, parser requirements may differ.
- The fastest path for coursework is to validate model predictions with Ultralytics first, then integrate the selected ONNX into DeepStream.

## 5. Validation Checklist

Before committing to a model:

- Can the weight file be downloaded?
- Can it run inference on one image/video?
- Are classes exactly what we need?
- Is license acceptable for coursework/team demo?
- Can it export to ONNX?
- Can TensorRT build an engine in the Savant/DeepStream container?
- Does Savant's YOLO converter parse the output correctly?
- Does it work on our target camera scenes?
- Do Kafka events still contain stable `track_id`, `crop_uri`, and `gpu_memory_ref` after model replacement?
