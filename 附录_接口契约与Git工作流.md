# 附录：全员共享的接口契约与 Git 工作流

## 1. Kafka 数据 Schema（人员1制定，人员2/3/6严格遵守）

单 Topic 按 `stream_id` 分区，JSON 结构：

```json
{
  "stream_id": "cam_001",
  "timestamp": 1714972800.123,
  "frame_id": 12045,
  "inference_fps": 25,
  "objects": [
    {
      "track_id": 42,
      "class": "person",
      "confidence": 0.92,
      "bbox": [100, 200, 150, 300],
      "roi_names": ["zone_A"],
      "attributes": {"helmet": true, "uniform": false},
      "events": ["entered_zone_A"],
      "reid_feature": [0.12, -0.05, ...]
    }
  ]
}
```

- **人员2**：填充 `track_id`、`bbox`、`class`、`attributes`。
- **人员3**：填充 `events`（进入/消失/属性变化），负责去重逻辑。
- **人员6**：填充 `roi_names`（后端区域逻辑计算后反写）和 `reid_feature`。

## 2. 视频流分层拓扑（人员1/2/3/4/5统一）

```
摄像头 RTSP
    ↓
[人员1: ZLMediaKit] ──→ 原始流 FLV/WebRTC ──→ [人员5: 前端 Canvas 渲染]
    ↓
[人员2/3: Savant Pipeline + OSD]
    ↓
带框 RTSP ──→ [人员4: Frigate 录像]
    ↓
Kafka ──→ [人员6: 区域逻辑/Re-ID] ──→ WebSocket ──→ [人员5: 前端仪表盘]
```

- **预览流**：人员5从 ZLMediaKit 拉原始流，WebSocket 接 Kafka 坐标，Canvas 画框。
- **录像流**：人员3输出的带 OSD RTSP 直接给人员4的 Frigate。
- **坐标系**：所有 `bbox` 统一为 `[x, y, w, h]`，基于原始分辨率，前端负责 Canvas 缩放适配。

## 3. RESTful API 规范（人员4/7制定，人员5调用）

| 接口 | 负责人 | 消费者 |
|:---|:---|:---|
| `/api/cameras` CRUD | 人员4 | 人员5（设备管理页面） |
| `/api/cameras/{id}/stream` 启停 | 人员4 | 人员5、人员1（按需拉流） |
| `/api/cameras/{id}/roi` 下发 | 人员7 | 人员5（ROI绘制后保存）、人员6（加载执行） |
| `/api/models/{id}/switch` 热更新 | 人员7 | 人员5（算法切换按钮） |
| `/api/search/reid` 以图搜图 | 人员6 | 人员5（上传图片/展示轨迹） |
| `/api/alerts` 告警查询 | 人员6 | 人员5（告警列表） |
| `/api/telemetry` 追踪数据 | 人员1 | 人员5（性能大盘） |

## 4. 配置中心 Schema（人员7制定，全组遵守）

```yaml
cam_001:
  model: "yolov8_person_vehicle"
  inference_fps: 5          # 人员7下发 → 人员2/7执行
  motion_mask: true         # 人员7下发 → 人员2执行
  rois:
    zone_A: {points: [[100,100], ...], rules: ["loitering:30"]}
  privacy_mask: true          # 人员7下发 → 人员3执行
```

## 5. Git 工作流与每日站会检查清单

| 检查项 | 负责人 | 验证方式 |
|:---|:---|:---|
| `shared/constants.py` 无冲突合并 | 组长 | Code Review |
| Kafka 消息 `msg_version` 均为 `1.0` | 全员 | 日志抓取 |
| `bbox_xywh` 坐标系基于原始分辨率 | 人员2/3/5 | 前端 Canvas 与视频对齐 |
| `track_id` 格式统一 | 人员2/3/6 | Kafka 消息抽查 |
| RTSP 流命名规范：`{cam_id}` 原始流，`{cam_id}_osd` 叠加流 | 人员1/3 | ZLMediaKit 后台 |
| API 统一前缀 `/api/v1/` | 人员4/7 | Postman 集合 |

**每日站会三句话模板**（每人必须回答）：
1. 昨天我完成了什么文件/函数的编写？
2. 今天我将对接谁的接口（上下游）？
3. 我是否遇到了阻塞（需要组长协调）？
