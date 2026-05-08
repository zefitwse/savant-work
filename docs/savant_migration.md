# Savant 实现与任务十一/十二接口

本文描述当前 Savant-only 版本的实现状态。原 DeepStream Python pipeline 已移除，当前运行入口是 `savant/module.yml`。

## 任务二：推理 Pipeline

Savant 模块：

```text
savant/module.yml
```

处理链路：

```text
video_loop source
  -> ZeroMQ input
  -> Savant module
      -> RuntimeControlProcessor
      -> primary_traffic_detector(PGIE)
      -> yolo_ppe_secondary(SGIE on person ROI)
      -> NvMultiObjectTracker
      -> EdgeEventProcessor(Kafka sparse events + track_id/crop_uri/gpu_memory_ref)
      -> PrivacyAwareDrawFunc(OSD + preview masking)
  -> ZeroMQ output(pub/sub)
  -> video file sink + ZLMediaKit RTMP masked sink
```

一级模型输出：

```text
person
vehicle: car/bicycle/motorcycle/bus/truck normalized
foreign_object: placeholder classes
```

二级模型输出：

```text
helmet: hardhat/no-hardhat
workwear: vest/no-vest
license_plate: interface reserved
```

## 任务三：结构化数据与 OSD

Kafka topic：

```text
deepstream.events
```

事件类型：

```text
object_entered
attribute_changed
object_expired
```

事件增强字段：

```text
track_id: 与 object_id 相同，来自 NvMultiObjectTracker
attributes.crop_uri: Re-ID 目标裁剪图路径
attributes.crop_status: pending_export / ok / frame_unavailable 等状态
attributes.gpu_memory_ref: DeepStream buffer 引用信息，包含 batch_id、frame_num、gst_buffer_ref、device_ptr_available
```

OSD 视频输出：

```text
rtsp://127.0.0.1:8554/live/ppt_cascade_masked
```

本地调试文件：

```text
runtime/savant-output/video.mov
runtime/savant-output/metadata.json
runtime/raw-output/video.mov
runtime/raw-output/metadata.json
runtime/crops/{camera_id}/{track_id}/*.jpg
```

目标裁剪图生成：

```powershell
python scripts/export_reid_crops.py `
  --metadata runtime\savant-output\metadata.json `
  --video runtime\raw-output\video.mov `
  --output-dir runtime\crops
```

## 任务十一：隐私保护与合规化

相关文件：

```text
coursework_savant/privacy_mask.py
coursework_savant/draw_func.py
scripts/zmq_to_zlm_rtmp.py
src/control_api.py
docker-compose.savant.yml
```

实现方式：

```text
1. Kafka 事件在 EdgeEventProcessor 中使用原始 bbox 构造，坐标不做遮蔽修改。
2. operator/guest 预览流使用 Savant OSD 输出，并在 PrivacyAwareDrawFunc 中对敏感区域做实时模糊。
3. 当前演示版在没有独立人脸模型时，对 person bbox 的头部区域做实时模糊。
4. 后续接入 face/license_plate 检测后，可直接将真实敏感 bbox 加入同一遮蔽逻辑。
5. admin raw 预览流由 raw Savant 分支输出，保留检测框但不做隐私遮蔽。
6. raw 本地输出 runtime/raw-output/video.mov，便于和 masked 输出截图对比。
```

权限分级接口：

```http
GET /preview/streams
X-User-Role: admin
```

返回规则：

```text
admin    -> rtsp://127.0.0.1:8554/live/ppt_cascade_raw     privacy_masked=false
operator -> rtsp://127.0.0.1:8554/live/ppt_cascade_masked  privacy_masked=true
guest    -> rtsp://127.0.0.1:8554/live/ppt_cascade_masked  privacy_masked=true
```

重要约定：

```text
Kafka 保留原始 bbox 坐标。
隐私模糊只作用于 Web/operator/guest 预览。
管理员 raw 预览用于演示权限分级，不提供给普通值班员。
当前 raw 预览流为管理员视角视频流。
当前 raw 本地输出文件为 runtime/raw-output/video.mov，包含检测框但不打码。
当前 masked 本地输出文件为 runtime/savant-output/video.mov，包含检测框并打码。
```

## 任务十二：云边端协同管理与 OpenTelemetry

相关文件：

```text
coursework_savant/model_switcher.py
coursework_savant/config_version.py
coursework_savant/telemetry.py
configs/otel-collector-config.yml
src/control_store.py
src/control_api.py
docker-compose.savant.yml
```

模型热更新接口：

```http
POST /models/hotswap
Content-Type: application/json

{
  "node_id": "edge-node-01",
  "detector": "pgie",
  "engine_path": "/workspace/deepstream_coursework/models/day.engine",
  "labels_path": "/workspace/deepstream_coursework/models/day_labels.txt",
  "reason": "daytime stockpile detection"
}
```

配置版本化接口：

```text
POST /configs/cameras
POST /configs/deploy
```

控制 API 会写入：

```text
runtime/edge_control.db
runtime/model_state.json
```

Savant 模块中的 `RuntimeControlProcessor` 会轮询 `runtime/model_state.json`。当前已完成 API、状态落库和 Savant 侧监听；真正运行中替换 `nvinfer` engine 的底层 reload hook 需要按最终部署的 Savant runtime 版本补齐。

OpenTelemetry：

```text
Collector 容器: coursework-otel-collector
OTLP gRPC: http://otel-collector:4317
OTLP HTTP: http://otel-collector:4318
Savant masked service.name: coursework-savant-masked
Savant raw service.name: coursework-savant-raw
Control API instrumentation: FastAPIInstrumentor
```

已导出的 Savant span：

```text
savant.event.process_frame
savant.reid.crop_export
savant.event.build
savant.kafka.publish
savant.runtime_control.hotswap_command
```

## 验证命令

```powershell
python scripts/test_savant_interfaces.py
.\scripts\run_full_test.ps1
```

`scripts/video_file_replay_loop.sh` 会无限循环推送 `test.mp4`。完整测试脚本会后台启动 source adapter，采样完成后主动停止 `source-video` 与 `source-video-raw`，再导出 Re-ID 目标裁剪图。

消费 Kafka：

```powershell
docker exec coursework-redpanda rpk topic consume deepstream.events --brokers localhost:9092 -n 5
```

检查 ZLMediaKit：

```powershell
docker logs coursework-zlm --tail 120
```

成功时日志应包含：

```text
媒体注册:rtsp://__defaultVhost__/live/ppt_cascade_masked
媒体注册:rtsp://__defaultVhost__/live/ppt_cascade_raw
H264[1280/720/25]
```

最新容器级验证结果：

```text
Kafka sample events: 14
EventsWithTrackId: 14
EventsWithCropUri: 10
EventsWithGpuMemoryRef: 10
Generated target crops: 50
OpenTelemetry Collector received Savant spans
```
