# 团队联调说明文档

本文档根据课程作业 PPT 要求和当前项目实现编写，面向除推理端核心开发外的所有同学，用于统一视频流、结构化事件、控制 API、隐私分级、Re-ID、云边管理和可观测性联调边界。

当前项目采用 Savant + NVIDIA DeepStream runtime 作为边缘推理节点，ZLMediaKit 作为流媒体服务，Redpanda/Kafka 作为事件总线，FastAPI + SQLite 作为控制面。其他模块请优先依赖本文约定的接口，不要直接耦合模型内部实现。

## 1. 当前系统范围

课程 PPT 的总体目标是建设一个基于 Savant/DeepStream 的分布式实时视频智能分析系统，至少支持两路 RTSP 视频流、多个推理模型、分布式架构与流媒体调度策略。

当前工程已经完成或预留的能力如下：

| 能力 | 当前实现状态 | 主要文件 |
| --- | --- | --- |
| 推理 Pipeline | Savant-only，原 DeepStream Python pipeline 已移除 | `savant/module_masked.yml`、`savant/module_raw.yml` |
| 一级检测 | YOLO COCO 检测 `person`、车辆类、异物占位类 | `models/primary_yolo_coco` |
| 二级 PPE 检测 | 对 `person` ROI 运行，输出 `hardhat/no-hardhat/vest/no-vest` | `models/yolo` |
| Tracker 去重 | 使用 `NvMultiObjectTracker`，只发稀疏事件 | `configs/tracker_config.txt` |
| Kafka 事件 | 写入 `deepstream.events` | `coursework_savant/savant_pipeline.py` |
| OSD 视频 | 输出 H.264 带框视频 | `coursework_savant/draw_func.py` |
| 双路预览 | masked 给操作员，raw 给管理员 | `docker-compose.savant.yml` |
| 隐私遮蔽 | operator/guest 预览中遮蔽人头部估计区域 | `coursework_savant/privacy_mask.py` |
| 控制 API | 健康检查、预览流、模型热更新、配置版本化、下发记录 | `src/control_api.py` |
| 自适应推理 | motion score、idle/alert 模式标签已接入 | `coursework_savant/adaptive_inference.py` |
| Re-ID 裁剪图 | Kafka 写入 `crop_uri`，后处理脚本生成 `runtime/crops` JPG | `coursework_savant/crop_exporter.py`、`scripts/export_reid_crops.py` |
| GPU 引用字段 | Kafka 写入 `gpu_memory_ref`，说明 batch/frame/buffer 引用和 device pointer 可用性 | `coursework_savant/crop_exporter.py` |
| OpenTelemetry | Savant PyFunc 与 Control API 支持 OTLP 导出，compose 内置 Collector | `coursework_savant/telemetry.py`、`configs/otel-collector-config.yml` |
| 前端演示 | Nginx 托管静态监控页面 | `frontend/index.html` |

## 2. 联调总架构

```text
摄像头 / RTSP / 测试视频 test.mp4
  -> Savant Source Adapter
  -> Savant Module masked 分支
      -> AdaptiveInferenceController
      -> RuntimeControlProcessor
      -> primary_traffic_detector
      -> yolo_ppe_secondary
      -> NvMultiObjectTracker
      -> EdgeEventProcessor
      -> PrivacyAwareDrawFunc
      -> Kafka: deepstream.events
      -> ZLMediaKit: ppt_cascade_masked
      -> runtime/savant-output
  -> Savant Module raw 分支
      -> 同模型链路
      -> RawDrawFunc
      -> ZLMediaKit: ppt_cascade_raw
      -> runtime/raw-output
```

masked 分支负责普通值班员预览和 Kafka 事件输出；raw 分支用于管理员分级预览，不重复写 Kafka，避免同一视频源产生重复事件。

## 3. 服务地址总表

### 3.1 宿主机地址

| 类型 | 地址 | 用途 |
| --- | --- | --- |
| 前端演示页 | `http://localhost:8000` | Raw/Masked 预览演示 |
| Control API | `http://127.0.0.1:18080` | 配置、热更新、预览流查询 |
| Kafka Broker | `localhost:9092` | 下游消费结构化事件 |
| Kafka Topic | `deepstream.events` | AI 目标事件 |
| Masked RTSP | `rtsp://127.0.0.1:8554/live/ppt_cascade_masked` | 操作员视频流 |
| Masked RTMP | `rtmp://127.0.0.1:1935/live/ppt_cascade_masked` | RTMP 预览或转封装 |
| Masked HTTP-FLV | `http://127.0.0.1:8080/live/ppt_cascade_masked.live.flv` | Web 播放候选 |
| Masked HLS | `http://127.0.0.1:8080/live/ppt_cascade_masked/hls.m3u8` | Web 播放候选 |
| Raw RTSP | `rtsp://127.0.0.1:8554/live/ppt_cascade_raw` | 管理员视频流 |
| Raw RTMP | `rtmp://127.0.0.1:1935/live/ppt_cascade_raw` | 管理员 RTMP 预览 |
| Raw HTTP-FLV | `http://127.0.0.1:8080/live/ppt_cascade_raw.live.flv` | 管理员 Web 播放候选 |
| Raw HLS | `http://127.0.0.1:8080/live/ppt_cascade_raw/hls.m3u8` | 管理员 Web 播放候选 |

### 3.2 容器内部地址

| 类型 | 地址 | 用途 |
| --- | --- | --- |
| Kafka | `kafka:19092` | Savant 写入事件 |
| ZLMediaKit RTMP masked | `rtmp://zlm/live/ppt_cascade_masked` | masked 分支推流 |
| ZLMediaKit RTMP raw | `rtmp://zlm/live/ppt_cascade_raw` | raw 分支推流 |
| 项目挂载目录 | `/workspace/deepstream_coursework` | 容器内项目根目录 |
| 模型热更新状态 | `/workspace/deepstream_coursework/runtime/model_state.json` | Savant 轮询读取 |

## 4. 启动与基础验收

首次运行或镜像变更后：

```powershell
.\scripts\run_full_test.ps1 -Build
```

日常完整启动：

```powershell
docker compose -f docker-compose.kafka.yml up -d
docker compose -f docker-compose.control.yml up -d --build
docker compose -f docker-compose.savant.yml up -d
```

只启动控制 API：

```powershell
.\scripts\run_control_api.ps1 -Build
```

消费 Kafka 样例：

```powershell
docker exec coursework-redpanda rpk topic consume deepstream.events --brokers localhost:9092 -n 10 -o start
```

检查推流注册：

```powershell
docker logs coursework-zlm --tail 120
```

成功时应看到 `ppt_cascade_masked` 和 `ppt_cascade_raw` 对应媒体注册日志。本地输出文件位于：

```text
runtime/savant-output/video.mov
runtime/savant-output/metadata.json
runtime/raw-output/video.mov
runtime/raw-output/metadata.json
```

最新容器级验证结果：

```text
验证时间: 2026-05-07
验证命令: .\scripts\run_full_test.ps1
Kafka 采样事件: 14
带 track_id 事件: 14
带 crop_uri 事件: 10
带 gpu_memory_ref 事件: 10
生成目标裁剪图: 50 张 JPG
OTEL Collector: 已收到 Savant spans
Masked 输出: runtime/savant-output/video.mov
Raw 输出: runtime/raw-output/video.mov
```

注意：测试视频由 `scripts/video_file_replay_loop.sh` 无限循环推送。一键脚本会后台启动 source adapter，采样完成后主动停止 `source-video` 和 `source-video-raw`，避免测试流程卡住。

## 5. Kafka 事件协议

Topic：

```text
deepstream.events
```

Message key：

```text
{camera_id}:{object_id}
```

事件不是逐帧数据，而是目标状态变化后的稀疏事件：

| event_type | 触发时机 | 下游建议 |
| --- | --- | --- |
| `object_entered` | Tracker 新建目标 ID | 告警、抓拍、看板新增目标 |
| `attribute_changed` | 语义属性变化，例如安全帽状态变化 | 属性告警、更新目标状态 |
| `object_expired` | 目标超过 TTL 未出现 | 结束轨迹、统计停留时长 |

JSON 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_type` | string | `object_entered`、`attribute_changed`、`object_expired` |
| `camera_id` | string | 摄像头或视频源 ID，当前 masked 示例为 `test_video` |
| `object_id` | integer | Savant/DeepStream Tracker ID，同一路流内短期稳定 |
| `track_id` | integer | 建议下游兼容字段，含义等同 `object_id`；任务 8 联调时可由后端映射补充 |
| `class_id` | integer | 归一化类别 ID |
| `class_name` | string | `person`、`vehicle`、`foreign_object` |
| `confidence` | number | 一级检测置信度 |
| `bbox.left` | number | 目标框左上角 x |
| `bbox.top` | number | 目标框左上角 y |
| `bbox.width` | number | 目标框宽度 |
| `bbox.height` | number | 目标框高度 |
| `attributes` | object | 二级属性，如 `helmet`、`workwear`、`license_plate`、`crop_uri`、`gpu_memory_ref` |
| `timestamp` | string | UTC ISO-8601 时间 |

当前代码实际输出 `object_id`，它来自 `track_id`。为了方便任务 8，后端或事件适配层可以额外复制一个 `track_id` 字段；若没有该字段，下游应使用 `object_id` 作为跟踪 ID。

类别约定：

| class_id | class_name | 来源 |
| --- | --- | --- |
| 0 | `person` | 一级检测 |
| 1 | `vehicle` | `car/bicycle/motorcycle/bus/truck` 归一 |
| 2 | `foreign_object` | 异物占位类 |

属性约定：

| 属性 | 可能值 | 当前状态 |
| --- | --- | --- |
| `helmet` | `hardhat`、`no-hardhat` | 已接入 PPE 二级模型 |
| `helmet_confidence` | number | helmet 属性置信度 |
| `workwear` | `vest`、`no-vest` | 已以 PPE 模型近似接入 |
| `workwear_confidence` | number | workwear 属性置信度 |
| `license_plate` | string | 接口预留，真实 OCR 待接入 |
| `crop_uri` | string | 任务 8 使用，目标裁剪图保存地址 |
| `gpu_memory_ref` | object/string | 任务 8 可选，目标 ROI 在 GPU 内存中的引用描述 |

示例：

```json
{
  "event_type": "object_entered",
  "camera_id": "test_video",
  "object_id": 15,
  "track_id": 15,
  "class_id": 0,
  "class_name": "person",
  "confidence": 0.9252,
  "bbox": {"left": 410.5, "top": 198.25, "width": 318.0, "height": 515.0},
  "attributes": {
    "helmet": "no-hardhat",
    "helmet_confidence": 0.8433,
    "crop_uri": "runtime/crops/test_video/15/20260506T023410127Z.jpg"
  },
  "timestamp": "2026-05-06T02:34:10.127+00:00"
}
```

## 6. 坐标、时间和对象主键

当前输出帧尺寸固定为：

```text
1280 x 720
```

所有 bbox 和 ROI 坐标均基于输出帧像素坐标：

```text
left/top: 目标框左上角
width/height: 目标框尺寸
polygon: [[x1, y1], [x2, y2], ...]
```

目标主键约定：

```text
摄像头主键: camera_id
短期目标主键: camera_id + object_id
Re-ID 输入跟踪 ID: track_id，若事件中暂无 track_id，则使用 object_id
```

时间戳使用 UTC ISO-8601。前端或后端展示时自行转换到本地时区。

## 7. Control API

控制 API 基础地址：

```text
http://127.0.0.1:18080
```

### 7.1 健康检查

```http
GET /health
```

响应：

```json
{"status": "ok"}
```

### 7.2 权限分级预览流

```http
GET /preview/streams
X-User-Role: admin
```

角色规则：

| 角色 | 返回流 | 是否遮蔽 | 用途 |
| --- | --- | --- | --- |
| `admin` | `ppt_cascade_raw` | false | 管理员全图预览 |
| `operator` | `ppt_cascade_masked` | true | 普通值班员预览 |
| `guest` | `ppt_cascade_masked` | true | 访客或低权限预览 |

### 7.3 模型热更新命令

```http
POST /models/hotswap
Content-Type: application/json

{
  "node_id": "edge-node-01",
  "detector": "pgie",
  "engine_path": "/workspace/deepstream_coursework/models/day.engine",
  "labels_path": "/workspace/deepstream_coursework/models/day_labels.txt",
  "reason": "day/night switch"
}
```

当前实现会落库到 `runtime/edge_control.db`，并写入 `runtime/model_state.json`。Savant 中的 `RuntimeControlProcessor` 会轮询该文件并把 active model 信息写入帧 tag。运行中真正替换 `nvinfer` engine 的底层 reload hook 仍需按最终 Savant runtime 版本补齐。

查询当前最近模型命令：

```http
GET /models/active
GET /models/active?node_id=edge-node-01
```

### 7.4 摄像头配置版本化

```http
POST /configs/cameras
Content-Type: application/json

{
  "camera_id": "cam01",
  "version": "2026-05-06-v1",
  "roi": [
    {
      "name": "work_area",
      "polygon": [[0, 0], [1280, 0], [1280, 720], [0, 720]]
    }
  ],
  "thresholds": {
    "person": 0.25,
    "vehicle": 0.4
  },
  "algorithm_params": {
    "ttl_frames": 90,
    "attribute_cooldown_frames": 30,
    "idle_fps": 5,
    "active_fps": 25,
    "motion_mask_enabled": true
  },
  "privacy": {
    "enabled": true,
    "masked_roles": ["operator", "guest"]
  }
}
```

查询摄像头最新配置：

```http
GET /configs/cameras/{camera_id}/latest
```

### 7.5 配置下发记录

```http
POST /configs/deploy
Content-Type: application/json

{
  "node_id": "edge-node-01",
  "camera_ids": ["cam01"],
  "config_version": "2026-05-06-v1"
}
```

查询下发记录：

```http
GET /configs/deployments
GET /configs/deployments?node_id=edge-node-01
```

## 8. 各任务联调说明

### 8.1 任务一：多协议流媒体接入与网关

PPT 要求支持 RTSP、RTMP、HTTP-FLV/HLS、GB/T 28181、ONVIF 等协议，并以 ZLMediaKit 作为多路流接入和分发核心。

当前推理端需要任务一提供：

| 信息 | 要求 |
| --- | --- |
| `camera_id` 命名规则 | 全组唯一，例如 `cam01`、`warehouse-east-01` |
| 原始 RTSP 地址 | 每路摄像头原始高码率流 |
| 预览流地址 | 如存在低码率预览流，也需给出 |
| 分辨率/帧率 | 建议对齐或可转换为 `1280x720` |
| 按需拉流策略 | 前端有人看或 Savant 节点有余量时再拉高码率流 |

当前推理端提供给任务一：

```text
Savant 输入: Source Adapter -> ZeroMQ -> Savant Module
测试输入: /workspace/deepstream_coursework/test.mp4
示例 SOURCE_ID: test_video
处理后 masked 输出: rtsp://127.0.0.1:8554/live/ppt_cascade_masked
处理后 raw 输出: rtsp://127.0.0.1:8554/live/ppt_cascade_raw
```

后续扩展到多路时，建议每路视频独立设置 `SOURCE_ID`，Kafka 中用 `camera_id` 区分。

### 8.2 任务二：推理 Pipeline

当前推理端采用可横向扩展的 Savant Module 形态，课程答辩中可以按“单节点演示 + 多容器/多节点横向扩展方案”说明。

当前模型级联：

```text
一级模型 primary_traffic_detector:
  person
  car/bicycle/motorcycle/bus/truck -> vehicle
  部分 COCO 物体类 -> foreign_object 占位

二级模型 yolo_ppe_secondary:
  输入: primary_traffic_detector.person ROI
  输出: hardhat/no-hardhat/vest/no-vest
  写入 attributes.helmet / attributes.workwear
```

Tracker 与去重：

```text
NvMultiObjectTracker 产生 track_id
EdgeEventProcessor 将 track_id 转为 object_id
SparseEventBuilder 只在进入、属性变化、过期时发 Kafka
```

### 8.3 任务三：结构化数据与 OSD

任务三应重点验证两件事：

```text
1. ZLMediaKit 中存在带框视频流
2. Kafka 中存在 JSON 结构化事件，且不是每帧重复发送
```

OSD 输出：

```text
Masked: rtsp://127.0.0.1:8554/live/ppt_cascade_masked
Raw:    rtsp://127.0.0.1:8554/live/ppt_cascade_raw
```

本地验证：

```powershell
docker logs coursework-zlm --tail 120
docker exec coursework-redpanda rpk topic consume deepstream.events --brokers localhost:9092 -n 10
```

### 8.4 任务四：前端监控系统

PPT 要求低延迟预览、多路分屏、实时仪表盘、热力图，并可扩展声纹、振动等信号。

前端建议消费：

| 功能 | 数据来源 |
| --- | --- |
| 视频墙 | HTTP-FLV/HLS，或经 go2rtc 转 WebRTC |
| 秒开低延迟预览 | 推荐 go2rtc/WebRTC，直接 RTSP 浏览器通常不可播 |
| 告警列表 | Kafka `deepstream.events` 经后端 WebSocket 转发 |
| 当前目标数 | 缓存 `object_entered` 到 `object_expired` 之间的目标状态 |
| 人流密度 | 按 `camera_id` 统计未过期 `person` |
| 热力图 | 使用 bbox 中心点或底边中心点累计 |
| 隐私预览 | 普通用户请求 `/preview/streams` 获取 masked 地址 |

如果展示 Savant 已画框视频，前端不需要重复画框。如果展示原始流并用 Canvas 画框，必须使用同一帧坐标系并处理播放器缩放比例。

### 8.5 任务五：Frigate 与 go2rtc 集成

推荐链路：

```text
Savant OSD Out -> ZLMediaKit RTSP -> go2rtc -> Frigate / React Web UI
```

Frigate 可以使用：

```text
rtsp://127.0.0.1:8554/live/ppt_cascade_masked
```

如果需要基于 AI 事件做录像标记或关键帧抓拍，请消费 Kafka：

```text
event_type = object_entered
class_name in [person, vehicle, foreign_object]
```

300 路摄像头管理 API 可先调用当前 Control API 做接口占位；大规模设备开关和算法切换建议由任务五/任务十二联合封装更上层 RESTful API。

### 8.6 任务六：区域关联逻辑

区域逻辑应基于 Kafka 事件，不建议重复跑检测。

必须使用字段：

```text
camera_id
object_id / track_id
class_name
bbox
timestamp
event_type
```

推荐目标点：

```text
x = bbox.left + bbox.width / 2
y = bbox.top + bbox.height
```

规则实现建议：

| 规则 | 实现方式 |
| --- | --- |
| 禁区告警 | 目标底边中心点落入 ROI polygon，且类别命中 |
| A-B Tripwire | 缓存同一 `camera_id + object_id` 的区域序列，先 A 后 B 触发 |
| 滞留检测 | 目标在 ROI 内持续超过 N 秒 |
| 密度阈值 | 统计 ROI 内未过期目标数，超过阈值发拥挤告警 |

动态 ROI 请写入：

```http
POST http://127.0.0.1:18080/configs/cameras
```

### 8.7 任务七：动态推理频率策略

PPT 要求平时 5fps 低频巡检，检测到疑似目标后提升到 25fps，并通过 Motion Masking 暂停静止画面推理。

当前实现：

```text
AdaptiveInferenceController 已写入 frame tag:
  adaptive_inference.mode = idle / alert
  adaptive_inference.should_process = true / false
  adaptive_inference.motion_score = 整数分数
  adaptive_inference.stats = processed/dropped 统计
```

当前配置：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `motion_threshold` | `50000.0` | 低于该值并持续冷却后恢复 idle |
| `alert_threshold` | `100000.0` | 高于该值进入 alert |
| `idle_frame_interval` | `5` | idle 模式下每 5 帧处理 1 帧 |
| `alert_cooldown_frames` | `30` | alert 恢复 idle 的冷却帧数 |
| `history_size` | `10` | 运动分数历史窗口 |
| `resize_width` | `64` | 运动检测缩放宽度 |
| `resize_height` | `64` | 运动检测缩放高度 |

注意：当前代码已计算模式和标签，但是否真正跳过后续 `nvinfer` 仍取决于 Savant runtime 对动态路由/跳帧 hook 的支持。答辩时可作为半实装能力演示，或通过双实例低频/高频容器方案演示。

### 8.8 任务八：Re-ID 与跨相机追踪

PPT 要求提取目标特征向量，在 Kafka 中对比不同摄像头的目标特征，实现跨镜头轨迹串联，并支持以图搜图。

任务 8 明确需要推理端提供以下数据：

| 数据 | 当前提供方式 | 后续推荐 |
| --- | --- | --- |
| 目标检测 bbox 坐标 | Kafka `bbox` 字段，坐标基于 `1280x720` | Re-ID 裁剪和特征提取直接使用 |
| track_id 目标跟踪 ID | Kafka 顶层字段 `track_id`，当前等同 `object_id` | Re-ID 使用 `camera_id + track_id` 作为单摄短期目标键 |
| 目标裁剪图 | Kafka `attributes.crop_uri` 给出路径，`scripts/export_reid_crops.py` 生成 JPG | 当前输出到 `runtime/crops/{camera_id}/{track_id}/...jpg` |
| GPU 内存地址 | Kafka `attributes.gpu_memory_ref` 给出 Savant/DeepStream buffer 引用信息 | 当前安全暴露 `gst_buffer_ref/batch_id/frame_num`；如果 Python binding 暴露 CUDA pointer，则 `device_ptr` 非空 |
| camera_id | Kafka `camera_id` | 跨相机匹配主键之一 |
| timestamp | Kafka `timestamp` | 跨镜头时序约束 |

推荐 Re-ID 输入事件格式：

```json
{
  "camera_id": "cam02",
  "track_id": 17,
  "object_id": 17,
  "class_name": "person",
  "bbox": {"left": 410.5, "top": 198.25, "width": 318.0, "height": 515.0},
  "crop_uri": "runtime/crops/cam02/17/frame_00001234_abcd1234.jpg",
  "gpu_memory_ref": {
    "kind": "nvds_buffer_surface",
    "device_ptr": null,
    "device_ptr_available": false,
    "gst_buffer_ref": "0x7f9e880548f0",
    "batch_id": 0,
    "frame_num": 1234
  },
  "timestamp": "2026-05-06T02:34:10.127+00:00"
}
```

推荐 Re-ID 输出独立 topic：

```text
reid.events
```

推荐 Re-ID 输出事件：

```json
{
  "event_type": "reid_matched",
  "global_id": "person-global-001",
  "camera_id": "cam02",
  "local_object_id": 17,
  "track_id": 17,
  "similarity": 0.86,
  "feature_version": "reid-model-v1",
  "timestamp": "2026-05-06T02:34:10.127+00:00"
}
```

当前实现方式：

```text
1. EdgeEventProcessor 在 person 事件 attributes 中写入 crop_uri、crop_status、gpu_memory_ref。
2. 为避免 PyDS surface 读取触发 native 崩溃，Savant PyFunc 默认不直接写 JPG。
3. 一键脚本会在停止无限循环 source 后运行 scripts/export_reid_crops.py。
4. export_reid_crops.py 读取 runtime/savant-output/metadata.json 与 runtime/raw-output/video.mov，按 bbox 生成目标裁剪图。
5. 裁剪图保存到 runtime/crops/{camera_id}/{track_id}/frame_xxxxxxxx_hash.jpg。
6. object_id/track_id 只保证单摄像头短期稳定，跨摄像头必须由 Re-ID 生成 global_id。
```

### 8.9 任务九：视频流质量诊断

PPT 要求诊断遮挡、移位、模糊、过暗、信号丢失，并在异常时触发自愈。

可用数据：

| 诊断项 | 数据来源 |
| --- | --- |
| 信号丢失 | ZLMediaKit、Source Adapter、Savant 日志 |
| 解码异常 | Savant module 日志 |
| 是否仍有输出 | `runtime/savant-output/video.mov` 或 ZLM 注册日志 |
| 模糊/过暗/遮挡 | VQD 自己抽帧计算 |
| 目标突然消失 | Kafka `object_expired` 可作为辅助信号 |

建议 VQD 使用独立 topic：

```text
video.quality.events
```

不要把视频质量事件混入 `deepstream.events`，避免污染目标检测事件。

### 8.10 任务十：运维与监控看板

PPT 要求用 Grafana + Prometheus 监控 FPS、延迟、GPU 利用率、显存占用，并在 RTSP 断连或 Savant 崩溃时通过 Webhook 通知。

关键容器：

| 容器 | 作用 |
| --- | --- |
| `coursework-savant-module-masked` | masked 推理模块 |
| `coursework-savant-module-raw` | raw 推理模块 |
| `coursework-savant-source` | masked 测试视频输入 |
| `coursework-savant-source-raw` | raw 测试视频输入 |
| `coursework-savant-video-sink-masked` | masked 本地视频输出 |
| `coursework-savant-video-sink-raw` | raw 本地视频输出 |
| `coursework-savant-zlm-sink-masked` | masked RTMP 桥接 |
| `coursework-savant-zlm-sink-raw` | raw RTMP 桥接 |
| `coursework-zlm` | ZLMediaKit |
| `coursework-redpanda` | Kafka/Redpanda |
| `coursework-control-api` | 控制 API |
| `coursework-frontend` | 前端静态页面 |

检查命令：

```powershell
docker ps -a
docker logs coursework-savant-module-masked --tail 120
docker logs coursework-savant-module-raw --tail 120
docker logs coursework-zlm --tail 120
docker exec coursework-redpanda rpk topic list --brokers localhost:9092
```

建议指标：

```text
输入 FPS
输出 FPS
端到端延迟
GPU 利用率
显存占用
Kafka topic 积压
容器健康状态
ZLMediaKit stream 注册状态
Control API 健康状态
```

### 8.11 任务十一：隐私保护与合规化

PPT 要求 Web 端预览时实时对人脸或敏感区域马赛克，但 Kafka 结构化数据保留原始坐标；管理员可见全图，普通值班员只能看到 AI 渲染后的带框视频。

当前实现：

```text
admin:
  /preview/streams 返回 raw 流
  privacy_masked = false

operator / guest:
  /preview/streams 返回 masked 流
  privacy_masked = true
```

重要约定：

```text
Kafka bbox 保留原始坐标，不因隐私遮蔽而修改。
隐私遮蔽只作用于预览视频，不作用于结构化数据。
当前没有独立人脸模型，演示版对 person bbox 的头部/上半身区域做模糊。
后续接入 face/license_plate 模型后，可直接把敏感 bbox 加入遮蔽列表。
```

### 8.12 任务十二：云边端协同管理与 OpenTelemetry

PPT 要求模型热更新、配置版本化、一键下发到不同计算节点。用户补充要求：任务 12 还需要配置 OpenTelemetry 导出，并需要 Savant 的 trace 数据。

当前已有控制面：

```text
GET  /health
POST /models/hotswap
GET  /models/active
POST /configs/cameras
GET  /configs/cameras/{camera_id}/latest
POST /configs/deploy
GET  /configs/deployments
```

任务 12 需要额外完成的可观测性契约：

| 数据 | 要求 | 推荐来源 |
| --- | --- | --- |
| Trace ID | 每路视频帧或采样帧的链路追踪 ID | Savant Source Adapter / PyFunc tag |
| Span | source、decode、infer、tracker、event、osd、sink 等阶段耗时 | Savant trace / 自定义 PyFunc 埋点 |
| Frame metadata | `camera_id`、`frame_num`、`timestamp`、`adaptive_inference.mode` | Savant frame_meta tag |
| Model metadata | 当前 detector、engine_path、模型版本 | `RuntimeControlProcessor` active model tag |
| Kafka publish span | 事件发送耗时、topic、partition、key | `EdgeEventProcessor._send_event` |
| Export endpoint | OTLP gRPC/HTTP Collector 地址 | OpenTelemetry Collector |

当前 compose 已配置 OpenTelemetry Collector，Savant masked/raw 分支和 Control API 都会尝试导出 OTLP trace。关键环境变量：

```text
OTEL_SERVICE_NAME=coursework-savant-masked
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_RESOURCE_ATTRIBUTES=edge.node_id=edge-node-01,pipeline.branch=masked
```

当前已接入的 trace span：

```text
savant.event.process_frame
savant.reid.crop_export
savant.event.build
savant.kafka.publish
savant.runtime_control.hotswap_command
```

建议 trace attributes：

```json
{
  "camera_id": "test_video",
  "frame_num": 1234,
  "source_id": "test_video",
  "object.count": 3,
  "kafka.topic": "deepstream.events"
}
```

当前落地状态：

```text
1. docker-compose.savant.yml 已增加 coursework-otel-collector。
2. configs/otel-collector-config.yml 使用 OTLP gRPC/HTTP receiver 和 debug exporter。
3. coursework_savant/telemetry.py 提供可选 OTEL 初始化；没有 Collector 时不阻塞主流程。
4. EdgeEventProcessor 已导出事件处理、crop export、event build、Kafka publish span。
5. RuntimeControlProcessor 已导出模型热更新命令 span。
6. Control API 已接入 OpenTelemetry FastAPI instrumentation。
7. 后续接 Grafana Tempo/Jaeger 时，只需替换 Collector exporter。
```

当前 `requirements.txt` 已加入：

```text
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp
opentelemetry-instrumentation-fastapi
```

Savant trace 数据的最低交付标准：

```text
能看到 Savant 模块内每个采样帧的 camera_id、frame_num。
能区分 event.process_frame、reid.crop_export、event.build、kafka.publish 阶段。
能在 coursework-otel-collector 日志中看到 detailed trace。
能把模型热更新命令和之后的 active_model tag 关联起来。
```

### 8.13 任务十三：扩展与分布式解耦

PPT 提到使用 ZeroMQ 或 Kafka 解耦 Adapter、Pipeline 和 Sink，并通过 OpenTelemetry 做全链路追踪。

当前项目已经使用：

```text
ZeroMQ: Source Adapter -> Savant Module -> Sink
Kafka: 结构化事件总线 deepstream.events
Docker Compose: 模块化容器编排
```

后续扩展方向：

```text
多 GPU 节点
多 Savant 实例
Kafka 分区
按 camera_id 做负载均衡
Triton 多模型服务
条件分支路由
前端 Canvas 自绘 OSD
OpenTelemetry 全链路追踪
```

## 9. 下游开发约定

全组统一遵守：

```text
1. 所有跨模块逻辑以 camera_id 作为摄像头主键。
2. 所有目标级逻辑以 camera_id + object_id/track_id 作为短期目标主键。
3. object_id 当前等同于 Tracker 输出的 track_id。
4. Re-ID 不能把 object_id 当作跨摄像头全局 ID，必须生成 global_id。
5. 所有区域、Canvas、热力图都使用 1280x720 坐标系。
6. 告警服务不得假设每帧都有消息，只能按事件驱动处理。
7. 新增字段优先放入 attributes，避免破坏主 schema。
8. 视频质量、Re-ID、运维告警建议使用独立 Kafka topic。
9. Kafka bbox 保留原始坐标；隐私遮蔽仅作用于普通用户预览视频。
10. 控制面 API 当前是可演示接口，真正 runtime engine reload 和大规模节点调度需继续补齐。
```

## 10. 当前限制

```text
1. 当前默认演示输入是 1 路 test.mp4，未实测 30-50 路生产吞吐。
2. 项目已经具备 raw/masked 双分支，但不是实际 2 路不同摄像头输入。
3. 车牌识别 license_plate 字段为预留，真实 OCR 模型待接入。
4. foreign_object 当前是异物占位类，不是专用异常异物模型。
5. 自适应推理已产生 mode/should_process tag，但真正跳过 nvinfer 仍需 Savant runtime hook 或多 pipeline 路由。
6. 目标裁剪图已通过后处理脚本生成；当前不是 PyFunc 内同步写图，适合课程联调和离线 Re-ID 输入。
7. gpu_memory_ref 已提供 buffer 引用和 device pointer 可用性标记；当前 PyDS 暴露的是安全引用信息，`device_ptr` 可能为 null。
8. OpenTelemetry 已接入 Collector 和 Savant PyFunc span；底层 DeepStream 原生算子级 span 仍需 Savant runtime 更深层 hook。
9. 本机 RTX 2060 6GB 适合课程演示，不建议承诺单机生产级 30-50 路；正式方案应按多容器、多节点、多 GPU 横向扩展说明。
```

## 11. 建议验收清单

联调前先跑：

```powershell
.\scripts\run_full_test.ps1 -Build
```

验收项：

| 项目 | 通过标准 |
| --- | --- |
| Kafka | `deepstream.events` 能消费到 `object_entered` 事件 |
| 视频 | ZLMediaKit 注册 `ppt_cascade_masked` 和 `ppt_cascade_raw` |
| OSD | 输出视频中能看到检测框和标签 |
| 隐私 | operator/guest 返回 masked，admin 返回 raw |
| 控制 API | `/health` 返回 `ok` |
| 配置版本化 | `/configs/cameras` 可写入并查询 |
| 模型热更新 | `/models/hotswap` 可写入 `runtime/model_state.json` |
| 任务 8 | Kafka 事件含 `bbox`、`object_id/track_id`、`attributes.crop_uri`、`attributes.gpu_memory_ref`，且 `runtime/crops` 有 JPG |
| 任务 12 | `coursework-otel-collector` 日志能看到 `savant.event.process_frame`、`savant.reid.crop_export`、`savant.kafka.publish` 等 span |
