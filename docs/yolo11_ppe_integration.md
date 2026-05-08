# YOLO11 PPE DeepStream Integration

当前 `models/yolo` 下的方案 4 模型已经接入当前 Savant/DeepStream runtime，并作为 `yolo_ppe_secondary` 在 `person` ROI 上运行。

## Model Files

```text
models/yolo/best.onnx
models/yolo/best.onnx_b1_gpu0_fp16.engine
models/yolo/model_config.json
models/yolo/ppe_labels.txt
```

类别：

```text
0 hardhat
1 no-hardhat
2 vest
3 no-vest
4 person
```

## TensorRT Binding

已验证 engine 绑定：

```text
input : images  FLOAT  (1, 3, 640, 640)
output: output0 FLOAT  (1, 9, 8400)
```

`output0` 是 YOLO 原始输出：

```text
4 bbox values + 5 class scores
```

因此 DeepStream 不能直接使用默认 bbox parser，需要自定义 parser。

## Build Commands

重新生成 TensorRT engine：

```powershell
.\scripts\build_yolo11_ppe_engine.ps1
```

## Savant Config

当前 PPE 模型配置在：

```text
savant/module_masked.yml
savant/module_raw.yml
```

其中 `yolo_ppe_secondary` 的关键设置：

```text
input.object: primary_traffic_detector.person
interval: 4
labels: hardhat / no-hardhat / vest / no-vest / person
converter: savant.converter.yolo.TensorToBBoxConverter
```

完整运行：

```powershell
.\scripts\run_full_test.ps1
```

Kafka topic：

```text
deepstream.events
```

ZLMediaKit 播放地址：

```text
rtsp://127.0.0.1:8554/live/ppt_cascade_masked
rtsp://127.0.0.1:8554/live/ppt_cascade_raw
```

## Verified Result

已在当前 Windows + WSL + DeepStream 环境验证：

- TensorRT 可以从 `best.onnx` 构建 `best.onnx_b1_gpu0_fp16.engine`。
- Savant/DeepStream `nvinfer` 可以反序列化 engine。
- Savant YOLO converter 可以输出检测框。
- Kafka/console 事件中已经出现：
  - `hardhat`
  - `no-hardhat`
  - `person`
- Kafka + ZLMediaKit 全链路已验证，Kafka person 事件中包含 PPE 属性、`track_id`、`crop_uri` 和 `gpu_memory_ref`。
- `runtime/crops` 可生成 Re-ID 目标裁剪图。
- OpenTelemetry Collector 可收到 Savant PyFunc spans。

示例事件：

```json
{
  "event_type": "object_entered",
  "camera_id": "cam01",
  "object_id": 20,
  "track_id": 20,
  "class_id": 0,
  "class_name": "person",
  "confidence": 0.5049,
  "bbox": {
    "left": 3.13,
    "top": 318.14,
    "width": 53.3,
    "height": 83.07
  },
  "attributes": {
    "helmet": "no-hardhat",
    "helmet_confidence": 0.8423,
    "crop_uri": "runtime/crops/cam01/20/frame_00000065_a2b17ffe.jpg",
    "gpu_memory_ref": {
      "kind": "nvds_buffer_surface",
      "device_ptr_available": false,
      "batch_id": 0,
      "frame_num": 65
    }
  },
  "timestamp": "2026-05-03T13:45:05.932+00:00"
}
```

## Notes

- 当前 Savant 版本把 PPE 模型作为二级 detector 使用，输入为一级 `person` ROI。
- `hardhat/no-hardhat` 会折叠成 `attributes.helmet`，`vest/no-vest` 会折叠成 `attributes.workwear`。
- 当前示例视频不是工地场景，检测效果只用于联调验证。正式展示建议换成安全帽/反光衣测试视频。
