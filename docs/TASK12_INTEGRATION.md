# 任务十二集成指南（ savant-work 项目）

## 文件放置

将本目录文件复制到 savant-work 项目对应位置：

```
savant-work/
├── src/
│   └── control_api.py              ← 替换或合并已有文件
├── config_center/                  ← 新建目录
│   ├── __init__.py
│   ├── database.py
│   ├── schemas.py
│   ├── version_manager.py
│   └── sync_agent.py
├── coursework_savant/
│   └── reconfigure_listener.py     ← 给人员2集成到 Savant
├── Dockerfile.control              ← 控制 API 镜像（可选）
└── runtime/                          ← SQLite 数据库自动创建于此
```

## 启动步骤

1. **启动基础设施**（Kafka + ZLMediaKit + Savant）：
   ```bash
   docker compose -f docker-compose.savant.yml up -d
   ```

2. **启动控制 API**（如果 docker-compose.control.yml 已包含则自动启动）：
   ```bash
   # 方式 A：Docker
   docker compose -f docker-compose.control.yml up -d

   # 方式 B：本地开发（推荐调试时使用）
   cd savant-work
   pip install fastapi uvicorn sqlalchemy pydantic requests kafka-python
   uvicorn src.control_api:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **验证 API**：
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/api/v1/models
   ```

## 与 Savant 节点对接（人员2 负责）

1. 在 `coursework_savant/savant_pipeline.py` 中导入：
   ```python
   from coursework_savant.reconfigure_listener import ReconfigureListener
   ```

2. 在 PyFunc 初始化时启动监听：
   ```python
   self.listener = ReconfigureListener(port=50051)
   self.listener.start()
   ```

3. 在 `process_frame` 中检查并应用指令：
   ```python
   cmd = self.listener.consume_command()
   if cmd and cmd["command_type"] == "MODEL_SWITCH":
       self.reload_engine(cmd["engine_path"], cmd.get("config_patch", {}))
   ```

4. 容器启动后向配置中心注册：
   ```bash
   curl -X POST http://localhost:8000/api/v1/nodes/register      -H "Content-Type: application/json"      -d '{"node_id":"savant-gpu-001","gpu_id":0,"api_endpoint":"http://savant-gpu-001:50051"}'
   ```

## 快速测试（无需 Savant 就绪）

```bash
# 1. 注册 Mock 节点
curl -X POST http://localhost:8000/api/v1/nodes/register   -H "Content-Type: application/json"   -d '{"node_id":"mock-node","gpu_id":0,"api_endpoint":"http://localhost:50051"}'

# 2. 注册摄像头
curl -X POST "http://localhost:8000/api/v1/cameras?cam_id=cam_001&src_url=rtsp://localhost/live/test"

# 3. 注册模型
curl -X POST http://localhost:8000/api/v1/models/register   -H "Content-Type: application/json"   -d '{"model_id":"night_fire","name":"夜间烟火检测","engine_path":"/models/night_fire.engine"}'

# 4. 保存 ROI
curl -X PUT http://localhost:8000/api/v1/cameras/cam_001/roi   -H "Content-Type: application/json"   -d '[{"name":"zone_A","type":"forbidden","points":[[100,100],[200,100],[200,200],[100,200]]}]'

# 5. 查询配置
curl http://localhost:8000/api/v1/cameras/cam_001/config

# 6. 热切换模型（如果 Savant 节点未就绪，会返回 failed，但数据库已更新）
curl -X POST http://localhost:8000/api/v1/models/night_fire/switch   -H "Content-Type: application/json"   -d '{"target_cam_id":"cam_001"}'

# 7. 查看版本历史
curl http://localhost:8000/api/v1/cameras/cam_001/versions

# 8. 回滚
curl -X POST "http://localhost:8000/api/v1/cameras/cam_001/rollback?version_id=v_20260511120000_cam_001"
```

## 答辩演示脚本

1. **一键切换模型**：Swagger UI → `POST /api/v1/models/{id}/switch` → 展示数据库变更 + 下发结果
2. **ROI 版本回滚**：先保存 ROI → 修改 ROI → 展示版本列表 → 回滚 → 验证恢复
3. **节点负载仪表盘**：`GET /api/v1/nodes` → 展示 GPU 和流数量
4. **端到端追踪**：结合已有 OpenTelemetry，展示配置下发指令的 Trace
