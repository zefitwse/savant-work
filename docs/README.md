# Savant Coursework

本工程当前只保留 Savant 版本，用于完成课程作业任务二、任务三、任务八、任务十一、任务十二的联调演示。原 DeepStream Python pipeline 已移除，Savant 镜像内部仍使用 NVIDIA DeepStream/GStreamer 作为运行时，这是 Savant 官方 DeepStream runtime 的正常依赖。

## 已实现功能

- 一级检测：`primary_traffic_detector` 使用 YOLO COCO ONNX，检测 `person`、车辆类和若干异物占位类。
- 类别归一：Kafka 中将 `car/bicycle/motorcycle/bus/truck` 归一为 `vehicle`，将部分 COCO 物体类作为 `foreign_object` 占位。
- 二级模型：`yolo_ppe_secondary` 只针对一级 `person` ROI 运行，识别 `hardhat/no-hardhat/vest/no-vest`。
- Tracker 去重：使用 `NvMultiObjectTracker`，Kafka 发送 `object_entered/attribute_changed/object_expired` 事件，而不是每帧发送；事件顶层包含 `track_id`。
- OSD 输出：Savant 输出带框 H.264 视频。
- ZLMediaKit：通过 RTMP 推送到 ZLMediaKit，并提供 RTSP/HTTP-FLV/HLS 播放地址。
- Kafka：事件写入 Redpanda/Kafka topic `deepstream.events`。
- 任务八接口：Kafka 事件提供 `bbox`、`track_id`、`attributes.crop_uri`、`attributes.gpu_memory_ref`，并生成 `runtime/crops` 目标裁剪图。
- 任务十一接口：已接入隐私遮蔽、管理员/值班员分级预览接口。
- 任务十二接口：已接入模型热更新、摄像头配置版本化、一键下发接口，并配置 OpenTelemetry OTLP trace 导出。

### 新增功能（任务七：动态推理频率策略）

- **动态推理频率策略 (Adaptive Inference)**：
  - 平时以 5fps 进行低频巡检，节省 GPU 算力
  - 检测到疑似目标（运动）时，自动提升至 25fps 全帧率
  - 获取更精准的轨迹和抓拍

- **静止过滤 (Motion Masking)**：
  - 在 Savant 前端引入简单的运动检测
  - 如果画面完全静止（如深夜的库房），自动暂停 DeepStream 推理
  - 运动阈值可配置，低于阈值时进入省电模式

- **双路输出**：
  - Raw 输出（管理员视角）：无隐私遮罩，显示完整画面
  - Masked 输出（操作员视角）：带隐私遮罩的画面
  - 两路视频同时输出，保持同步

- **前端监控界面**：
  - 实时展示 Raw 和 Masked 双路视频
  - 支持延迟模式切换（流畅/低延迟）
  - 无限循环播放测试视频

### 新增功能（任务八/十二：Re-ID 输入与链路追踪）

- **Re-ID 目标裁剪图**：
  - Kafka person 事件中写入 `attributes.crop_uri`
  - 一键脚本在停止无限循环 source 后，使用 `runtime/savant-output/metadata.json` 与 `runtime/raw-output/video.mov` 生成 JPG 裁剪图
  - 裁剪图输出到 `runtime/crops/{camera_id}/{track_id}/`
- **GPU 引用字段**：
  - Kafka person 事件中写入 `attributes.gpu_memory_ref`
  - 当前包含 `gst_buffer_ref`、`batch_id`、`frame_num` 和 `device_ptr_available`
  - 当 PyDS/Savant binding 安全暴露 CUDA device pointer 时，`device_ptr` 可变为非空
- **OpenTelemetry Trace**：
  - `docker-compose.savant.yml` 已加入 `coursework-otel-collector`
  - Savant PyFunc 导出 `savant.event.process_frame`、`savant.reid.crop_export`、`savant.event.build`、`savant.kafka.publish`
  - Control API 接入 FastAPI instrumentation

## 当前验证结果

在 Windows 10 + WSL2 + Docker Desktop + RTX 2060 6GB 上已验证：

```text
Savant module: healthy
Source adapter: 约 20-30 FPS，循环读取 test.mp4
Kafka topic: deepstream.events 可消费到 JSON 事件
Kafka 事件: 包含 track_id、crop_uri、gpu_memory_ref
Re-ID crops: runtime/crops 下可生成 50 张示例目标裁剪图
OpenTelemetry: coursework-otel-collector 可收到 Savant spans
ZLMediaKit: 已注册 rtsp://__defaultVhost__/live/ppt_cascade_masked
ZLMediaKit: 已注册 rtsp://__defaultVhost__/live/ppt_cascade_raw
本地输出: runtime/savant-output/metadata.json 与 video.mov
本地输出: runtime/raw-output/video.mov
前端界面: http://localhost:8000
```

Kafka 样例：

```json
{
  "event_type": "object_entered",
  "camera_id": "test_video",
  "object_id": 2,
  "track_id": 2,
  "class_id": 0,
  "class_name": "person",
  "confidence": 0.4369,
  "bbox": {"left": 432.92, "top": 103.12, "width": 222.03, "height": 499.99},
  "attributes": {
    "helmet": "hardhat",
    "helmet_confidence": 0.8677,
    "crop_uri": "runtime/crops/test_video/2/frame_00000005_9b6aacaf.jpg",
    "gpu_memory_ref": {
      "kind": "nvds_buffer_surface",
      "device_ptr": null,
      "device_ptr_available": false,
      "gst_buffer_ref": "0x7f9e880548f0",
      "batch_id": 0,
      "frame_num": 5
    }
  },
  "timestamp": "2026-05-05T21:19:40.289+00:00"
}
```

## 启动命令

首次或依赖变化后构建 Savant 自定义镜像：

```powershell
.\scripts\run_savant_module.ps1 -PullImages -Build
```

日常启动（双路输出 + 前端）：

```powershell
docker compose -f docker-compose.savant.yml up -d
```

完整容器级验收（会处理无限循环视频 source，采样后主动停止 source）：

```powershell
.\scripts\run_full_test.ps1
```

只启动控制 API：

```powershell
.\scripts\run_control_api.ps1 -Build
```

消费 Kafka：

```powershell
docker exec coursework-redpanda rpk topic consume deepstream.events --brokers localhost:9092 -n 10
```

查看 ZLMediaKit 推流是否注册：

```powershell
docker logs coursework-zlm --tail 120
```

停止 Savant 链路：

```powershell
docker compose -f docker-compose.savant.yml down -v
```

停止 Kafka：

```powershell
docker compose -f docker-compose.kafka.yml down
```

## 播放地址

### 宿主机播放

**Masked 输出（操作员视角）：**
```text
RTSP:     rtsp://127.0.0.1:8554/live/ppt_cascade_masked
RTMP:     rtmp://127.0.0.1:1935/live/ppt_cascade_masked
HTTP-FLV: http://127.0.0.1:8080/live/ppt_cascade_masked.live.flv
HLS:      http://127.0.0.1:8080/live/ppt_cascade_masked/hls.m3u8
```

**Raw 输出（管理员视角）：**
```text
RTSP:     rtsp://127.0.0.1:8554/live/ppt_cascade_raw
RTMP:     rtmp://127.0.0.1:1935/live/ppt_cascade_raw
HTTP-FLV: http://127.0.0.1:8080/live/ppt_cascade_raw.live.flv
HLS:      http://127.0.0.1:8080/live/ppt_cascade_raw/hls.m3u8
```

### 前端监控界面

```text
前端界面: http://localhost:8000
```

## 关键文件

```text
savant/module.yml                         Savant Cascade 模块（原始配置）
savant/module_masked.yml                  Masked 输出模块配置（带隐私遮罩）
savant/module_raw.yml                     Raw 输出模块配置（无隐私遮罩）
coursework_savant/savant_pipeline.py      Kafka 事件、热更新监听 PyFunc
coursework_savant/event_builder.py        去重与事件构造
coursework_savant/privacy_mask.py         隐私遮蔽逻辑
coursework_savant/draw_func.py            绘制函数（RawDrawFunc/PrivacyAwareDrawFunc）
coursework_savant/adaptive_inference.py   自适应推理控制器（动态帧率）
coursework_savant/crop_exporter.py        Re-ID crop_uri 与 gpu_memory_ref 事件增强
coursework_savant/telemetry.py            OpenTelemetry 初始化与 span 工具
scripts/zmq_to_zlm_rtmp.py                Savant ZeroMQ 到 ZLMediaKit RTMP 桥接
scripts/video_file_replay_loop.sh         无限循环视频重放脚本
scripts/export_reid_crops.py              基于 metadata + raw 视频导出目标裁剪图
scripts/run_full_test.ps1                 完整测试脚本
docker-compose.savant.yml                 Savant + Source + Sink + ZLMediaKit + 前端
docker-compose.kafka.yml                  Redpanda/Kafka
docker-compose.control.yml                控制 API
configs/otel-collector-config.yml         OpenTelemetry Collector 配置
src/control_api.py                        任务十一/十二 HTTP API
docs/team_integration.md                  团队联调接口文档
docs/savant_migration.md                  Savant 实现说明
frontend/index.html                       前端监控界面
```

## 自适应推理配置

自适应推理控制器支持以下配置参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| motion_threshold | 50000.0 | 运动阈值，低于此值判定为静止 |
| alert_threshold | 100000.0 | 告警阈值，高于此值触发高频推理 |
| idle_frame_interval | 5 | 空闲模式下每 N 帧处理 1 帧（约 5fps） |
| alert_cooldown_frames | 30 | 告警冷却帧数，静止持续此帧数后恢复低频 |
| history_size | 10 | 运动历史窗口大小 |
| resize_width | 64 | 运动检测时图像缩放宽度 |
| resize_height | 64 | 运动检测时图像缩放高度 |

## 系统差异

Windows 10/11 推荐：

- 使用 WSL2 + Docker Desktop。
- Docker Desktop 开启 WSL2 backend。
- NVIDIA 驱动需支持 WSL GPU。
- `.wslconfig` 建议至少 `memory=6GB`、`swap=6GB`。

Linux 推荐：

- 安装 NVIDIA Container Toolkit。
- 使用同一套 Docker Compose 命令。
- 服务器级 GPU 可进一步提高多路吞吐。

## 当前限制

- 车牌识别和工服识别接口已预留，真实车牌/OCR、工服模型还需要替换业务模型后接入。
- 热更新 API 已能写入命令并被 Savant PyFunc 读取，运行中无重启切换 `nvinfer` engine 的底层 reload hook 仍保留在 `RuntimeControlProcessor` 中待按最终 Savant 版本实现。
- 目标裁剪图当前由后处理脚本从 raw 视频和 Savant metadata 导出，不在 PyFunc 内同步写图，以避免直接读取 PyDS surface 时触发 native 崩溃。
- `gpu_memory_ref.device_ptr` 当前可能为 `null`，表示 Python binding 未安全暴露 CUDA pointer；仍保留 `gst_buffer_ref/batch_id/frame_num` 供同节点扩展。
- OpenTelemetry 已导出 Savant PyFunc 和 Control API trace，底层 DeepStream 原生算子级 trace 仍需更深层 runtime hook。
- 本机 RTX 2060 6GB 适合课程演示，不建议承诺单机 30-50 路生产吞吐；30-50 路应按多容器、多节点横向扩展评估。
