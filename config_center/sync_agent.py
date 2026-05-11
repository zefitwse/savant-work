"""
config_center/sync_agent.py
配置下发引擎：HTTP 点对点 + Kafka 广播双通道
与 savant-work 的 coursework_savant/savant_pipeline.py 对接
"""
import json
import time
import requests
from typing import Optional, Dict, Any
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import NoBrokersAvailable

# 与 savant-work 对齐：Kafka broker 和 topic
KAFKA_BROKERS = "redpanda:9092"          # docker-compose.savant.yml 中的服务名
COMMAND_TOPIC = "vsa.commands"           # 控制指令 topic
# 兼容已有项目的 deepstream.events
EVENT_TOPIC = "deepstream.events"

class SyncAgent:
    def __init__(self):
        self.use_kafka = False
        self.producer = None
        self.mock_queue: list = []

        try:
            self.producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKERS,
                value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
                request_timeout_ms=3000,
            )
            self.use_kafka = True
        except NoBrokersAvailable:
            print("[SyncAgent] Kafka not available, falling back to HTTP-only mode")

    def send_to_node(self, api_endpoint: str, command: dict, timeout: int = 30) -> dict:
        """HTTP 点对点下发到 Savant 节点

        目标端点：与 savant-work 的 control_api.py 或 savant_pipeline.py 对接
        如果 Savant 节点实现了 /internal/reconfigure，则直接调用
        """
        url = f"{api_endpoint.rstrip('/')}/internal/reconfigure"
        try:
            resp = requests.post(url, json=command, timeout=timeout)
            resp.raise_for_status()
            return {"channel": "http", "status": "delivered", "response": resp.json()}
        except requests.exceptions.ConnectionError:
            return {"channel": "http", "status": "failed", "error": "Connection refused"}
        except requests.exceptions.Timeout:
            return {"channel": "http", "status": "failed", "error": "Timeout"}

    def broadcast_command(self, command: dict):
        """Kafka 广播：所有节点都消费"""
        if self.use_kafka and self.producer:
            self.producer.send(COMMAND_TOPIC, command)
            return {"channel": "kafka", "status": "broadcasted"}
        else:
            self.mock_queue.append(command)
            return {"channel": "mock_queue", "status": "queued"}

    def notify_config_reload(self, cam_id: str, target_node_id: Optional[str] = None):
        """通知 Savant 节点重载配置"""
        command = {
            "command_type": "CONFIG_RELOAD",
            "cam_id": cam_id,
            "timestamp": time.time(),
        }
        if target_node_id:
            # 点对点 HTTP
            # 实际应从数据库查 node.api_endpoint
            return self.send_to_node(f"http://{target_node_id}:50051", command)
        else:
            return self.broadcast_command(command)

    def send_model_switch(self, node_api_endpoint: str, model_id: str, engine_path: str,
                          config_patch: Optional[dict] = None, cam_id: Optional[str] = None):
        """发送模型热切换指令"""
        command = {
            "command_type": "MODEL_SWITCH",
            "cam_id": cam_id,
            "model_id": model_id,
            "engine_path": engine_path,
            "config_patch": config_patch or {},
            "timestamp": time.time(),
        }
        return self.send_to_node(node_api_endpoint, command)

# 单例
sync_agent = SyncAgent()
