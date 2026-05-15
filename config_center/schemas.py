"""
config_center/schemas.py
Pydantic 请求/响应模型，与 savant-work Kafka 事件格式对齐
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class BBox(BaseModel):
    left: float
    top: float
    width: float
    height: float

class ROIUpdate(BaseModel):
    name: str
    type: str = Field(..., pattern="^(forbidden|warning)$")
    points: List[List[float]]           # [[x,y], ...]

class RuleUpdate(BaseModel):
    rule_type: str = Field(..., pattern="^(tripwire|loitering|density)$")
    params: Dict[str, Any]              # {"from":"A","to":"B"} 或 {"threshold_sec":30}

class ModelRegister(BaseModel):
    model_id: str
    name: str
    engine_path: str                    # Savant 容器内绝对路径
    config_patch: Optional[Dict[str, Any]] = None
    description: Optional[str] = None

class SwitchModelRequest(BaseModel):
    target_cam_id: Optional[str] = None   # null = 全局切换

class NodeRegister(BaseModel):
    node_id: str
    gpu_id: int
    api_endpoint: str
    max_streams: int = 10

class CameraConfigOut(BaseModel):
    cam_id: str
    src_url: str
    enabled: bool
    assigned_node_id: Optional[str]
    current_model_id: Optional[str]
    infer_fps: int
    motion_threshold: int
    motion_mask: bool
    privacy_mask: bool
    permission_level: str
    rois: List[Dict[str, Any]]
    rules: List[Dict[str, Any]]

class ConfigVersionOut(BaseModel):
    version_id: str
    cam_id: str
    created_by: str
    created_at: datetime
    snapshot_preview: Dict[str, Any]    # 解析后的快照摘要

class CommandPayload(BaseModel):
    """下发给 Savant 节点的指令格式，与 coursework_savant/savant_pipeline.py 对齐"""
    command_type: str = Field(..., pattern="^(MODEL_SWITCH|CONFIG_RELOAD)$")
    cam_id: Optional[str] = None
    model_id: Optional[str] = None
    engine_path: Optional[str] = None
    config_patch: Optional[Dict[str, Any]] = None
    rois: Optional[List[Dict[str, Any]]] = None
    rules: Optional[List[Dict[str, Any]]] = None
    timestamp: float
