"""
config_center/sync_agent.py
配置下发引擎：HTTP 点对点 + Kafka 广播 + 文件写入（兼容 ModelSwitchWatcher）

与 savant-work 的 coursework_savant/model_switcher.py 对接：
- ModelSwitchWatcher 轮询 /workspace/deepstream_coursework/runtime/model_state.json
- 本模块在 HTTP 推送的同时写入该文件，实现零侵入热更新
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from kafka import KafkaProducer
    from kafka.errors import NoBrokersAvailable
except ImportError:
    KafkaProducer = None
    NoBrokersAvailable = Exception

KAFKA_BROKERS = "redpanda:9092"
COMMAND_TOPIC = "vsa.commands"

# Savant 文件监控路径（与 model_switcher.py 严格对齐）
SAVANT_RUNTIME_DIR = Path("/workspace/deepstream_coursework/runtime")
MODEL_STATE_PATH = SAVANT_RUNTIME_DIR / "model_state.json"


class SyncAgent:
    def __init__(self):
        self.use_kafka = False
        self.producer = None
        self.mock_queue: list = []

        if KafkaProducer is None:
            print("[SyncAgent] kafka-python not installed, falling back to HTTP+File mode")
            return

        try:
            self.producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKERS,
                value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
                request_timeout_ms=3000,
            )
            self.use_kafka = True
        except NoBrokersAvailable:
            print("[SyncAgent] Kafka not available, falling back to HTTP+File mode")
    
    def send_to_node(self, api_endpoint: str, command: dict, timeout: int = 30) -> dict:
        """HTTP 点对点下发"""
        url = f"{api_endpoint.rstrip('/')}/internal/reconfigure"
        try:
            import requests
            resp = requests.post(url, json=command, timeout=timeout)
            resp.raise_for_status()
            return {"channel": "http", "status": "delivered", "response": resp.json()}
        except Exception as e:
            return {"channel": "http", "status": "failed", "error": str(e)}
    
    def broadcast_command(self, command: dict):
        """Kafka 广播"""
        if self.use_kafka and self.producer:
            self.producer.send(COMMAND_TOPIC, command)
            return {"channel": "kafka", "status": "broadcasted"}
        else:
            self.mock_queue.append(command)
            return {"channel": "mock_queue", "status": "queued"}
    
    def _write_model_state_json(self, model_id: str, engine_path: str,
                                labels_path: Optional[str] = None,
                                node_id: str = "edge-node-01") -> dict:
        """
        写入 Savant 监控的 model_state.json
        这是与 ModelSwitchWatcher.poll() 对接的关键！
        文件格式必须与 model_switcher.py 期望的完全一致：
        {
          "id": <递增整数>,
          "created_at": "<ISO时间>",
          "payload": {
            "node_id": "...",
            "detector": "<模型名>",
            "engine_path": "<.engine路径>",
            "labels_path": "<可选>"
          }
        }
        """
        try:
            SAVANT_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            
            # 读取现有 id 并递增
            current_id = 0
            if MODEL_STATE_PATH.exists():
                try:
                    old = json.loads(MODEL_STATE_PATH.read_text())
                    current_id = int(old.get("id", 0))
                except Exception:
                    pass
            
            state = {
                "id": current_id + 1,
                "created_at": datetime.utcnow().isoformat(),
                "payload": {
                    "node_id": node_id,
                    "detector": model_id,
                    "engine_path": engine_path,
                    "labels_path": labels_path,
                }
            }
            MODEL_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
            return {
                "channel": "file",
                "status": "written",
                "path": str(MODEL_STATE_PATH),
                "id": current_id + 1,
            }
        except Exception as e:
            return {"channel": "file", "status": "failed", "error": str(e)}
    
    def notify_config_reload(self, cam_id: str, target_node_id: Optional[str] = None):
        """通知 Savant 节点重载配置（ROI/规则/阈值）"""
        command = {
            "command_type": "CONFIG_RELOAD",
            "cam_id": cam_id,
            "timestamp": time.time(),
        }
        if target_node_id:
            return self.send_to_node(f"http://{target_node_id}:50051", command)
        else:
            return self.broadcast_command(command)
    
    def send_model_switch(self, node_api_endpoint: str, model_id: str, engine_path: str,
                          config_patch: Optional[dict] = None, cam_id: Optional[str] = None,
                          labels_path: Optional[str] = None) -> dict:
        """
        发送模型热切换指令。
        
        双通道策略：
        1. HTTP 推送到 Savant 节点（如果实现了 reconfigure_listener）
        2. 写入 model_state.json（兼容 ModelSwitchWatcher 轮询，零侵入！）
        
        人员2 的 ModelSwitchWatcher.poll() 会在下一帧自动检测到变更。
        """
        # 1. HTTP 推送（可选）
        http_result = None
        if node_api_endpoint:
            command = {
                "command_type": "MODEL_SWITCH",
                "cam_id": cam_id,
                "model_id": model_id,
                "engine_path": engine_path,
                "config_patch": config_patch or {},
                "timestamp": time.time(),
            }
            http_result = self.send_to_node(node_api_endpoint, command)
        
        # 2. 写入 model_state.json（核心：兼容现有 ModelSwitchWatcher）
        file_result = self._write_model_state_json(
            model_id=model_id,
            engine_path=engine_path,
            labels_path=labels_path,
        )
        
        return {
            "status": "switch_issued",
            "http_result": http_result,
            "file_result": file_result,
        }


# 单例
sync_agent = SyncAgent()
