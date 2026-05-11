from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Header, HTTPException, UploadFile, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# 原有导入
from coursework_savant.reid import ReIDFeatureExtractor, ReIDSQLiteStore, decode_event_feature
from coursework_savant.telemetry import instrument_fastapi

try:
    from .control_store import ControlStore
except ImportError:
    from control_store import ControlStore

# 任务十二新增导入
from config_center.database import get_db, Camera, Model, Node, ROI, Rule, ConfigVersion
from config_center.schemas import (
    CameraConfigOut, ROIUpdate, RuleUpdate, ModelRegister,
    SwitchModelRequest, NodeRegister, ConfigVersionOut
)
from config_center.version_manager import create_snapshot, rollback
from config_center.sync_agent import sync_agent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
MODEL_STATE_PATH = RUNTIME_DIR / "model_state.json"

app = FastAPI(title="DeepStream/Savant Edge Control API", version="0.2.0")
instrument_fastapi(app)
store = ControlStore(PROJECT_ROOT / "runtime" / "edge_control.db")
reid_model_path = os.getenv("REID_MODEL_PATH")
reid_extractor = ReIDFeatureExtractor(model_path=Path(reid_model_path) if reid_model_path else None)
reid_store = ReIDSQLiteStore(PROJECT_ROOT / "runtime" / "edge_control.db")


# ==================== 原有 Pydantic 模型（完全保留） ====================

class HotSwapRequest(BaseModel):
    node_id: str = "edge-node-01"
    detector: str = Field(..., description="Detector name, for example pgie or fire_detector.")
    engine_path: str = Field(..., description="Absolute path inside the inference container.")
    labels_path: Optional[str] = None
    reason: str = "manual"


class CameraConfigRequest(BaseModel):
    camera_id: str
    version: str
    roi: List[Dict[str, Any]] = Field(default_factory=list)
    thresholds: Dict[str, float] = Field(default_factory=dict)
    algorithm_params: Dict[str, Any] = Field(default_factory=dict)
    privacy: Dict[str, Any] = Field(default_factory=dict)


class DeployRequest(BaseModel):
    node_id: str
    camera_ids: List[str]
    config_version: Optional[str] = None


class ReIDEventRequest(BaseModel):
    event: Dict[str, Any] = Field(..., description="Kafka object event with attributes.crop_uri.")


class ReIDBase64SearchRequest(BaseModel):
    image_base64: str
    top_k: int = Field(default=20, ge=1, le=100)


# ==================== 原有路由（完全保留） ====================

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "control-api", "version": "0.2.0"}


@app.get("/preview/streams")
def preview_streams(
    x_user_role: str = Header(default="operator"),
) -> Dict[str, Any]:
    role = x_user_role.lower()
    if role == "admin":
        return {
            "role": role,
            "rtsp_url": "rtsp://127.0.0.1:8554/live/ppt_cascade_raw",
            "rtmp_url": "rtmp://127.0.0.1:1935/live/ppt_cascade_raw",
            "http_flv_url": "http://127.0.0.1:8080/live/ppt_cascade_raw.live.flv",
            "hls_url": "http://127.0.0.1:8080/live/ppt_cascade_raw/hls.m3u8",
            "local_output": str(PROJECT_ROOT / "runtime" / "raw-output" / "video.mp4"),
            "policy": "raw_full_frame",
            "privacy_masked": False,
            "description": "Admin preview. Full OSD frame without privacy masking.",
        }
    return {
        "role": role,
        "rtsp_url": "rtsp://127.0.0.1:8554/live/ppt_cascade_masked",
        "rtmp_url": "rtmp://127.0.0.1:1935/live/ppt_cascade_masked",
        "http_flv_url": "http://127.0.0.1:8080/live/ppt_cascade_masked.live.flv",
        "hls_url": "http://127.0.0.1:8080/live/ppt_cascade_masked/hls.m3u8",
        "local_output": str(PROJECT_ROOT / "runtime" / "savant-output" / "video.mov"),
        "policy": "masked_osd_preview",
        "privacy_masked": True,
        "description": "Operator preview. OSD frame with face/sensitive preview regions masked.",
    }


@app.post("/models/hotswap")
def hot_swap(request: HotSwapRequest) -> Dict[str, Any]:
    """模型热切换（增强版：同时尝试 HTTP 推送到已注册节点）"""
    engine_path = Path(request.engine_path)
    if not request.engine_path.endswith(".engine"):
        raise HTTPException(status_code=400, detail="engine_path must point to a .engine file.")

    # 1. 原有逻辑：存入 ControlStore
    record = store.save_model_switch(
        node_id=request.node_id,
        detector=request.detector,
        engine_path=str(engine_path),
        labels_path=request.labels_path,
        reason=request.reason,
    )
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_STATE_PATH.write_text(
        record_to_json(record),
        encoding="utf-8",
    )

    # 2. 新增：尝试 HTTP 推送到 Savant 节点（如果节点已注册）
    db = next(get_db())
    node = db.query(Node).filter(Node.node_id == request.node_id).first()
    push_result = None
    if node and node.api_endpoint:
        push_result = sync_agent.send_model_switch(
            node.api_endpoint,
            model_id=request.detector,
            engine_path=str(engine_path),
            config_patch={"labels_path": request.labels_path} if request.labels_path else {},
        )

    return {
        "id": record.id,
        "created_at": record.created_at,
        "payload": record.payload,
        "apply_mode": "savant_runtime_watches_runtime_model_state",
        "active_push": push_result,  # 新增：推送结果
    }


@app.get("/models/active")
def active_model(node_id: Optional[str] = None) -> Dict[str, Any]:
    record = store.latest_model_switch(node_id=node_id)
    if record is None:
        return {"payload": None}
    return {"id": record.id, "created_at": record.created_at, "payload": record.payload}


@app.post("/configs/cameras")
def save_camera_config(request: CameraConfigRequest) -> Dict[str, Any]:
    record = store.save_camera_config(
        camera_id=request.camera_id,
        version=request.version,
        roi=request.roi,
        thresholds=request.thresholds,
        algorithm_params=request.algorithm_params,
        privacy=request.privacy,
    )
    return {"id": record.id, "created_at": record.created_at, "payload": record.payload}


@app.get("/configs/cameras/{camera_id}/latest")
def latest_camera_config(camera_id: str) -> Dict[str, Any]:
    record = store.latest_camera_config(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="camera config not found")
    return {"id": record.id, "created_at": record.created_at, "payload": record.payload}


@app.post("/configs/deploy")
def deploy_config(request: DeployRequest) -> Dict[str, Any]:
    record = store.save_deployment(
        node_id=request.node_id,
        camera_ids=request.camera_ids,
        config_version=request.config_version,
    )
    return {"id": record.id, "created_at": record.created_at, "payload": record.payload}


@app.get("/configs/deployments")
def deployments(node_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "items": [
            {"id": item.id, "created_at": item.created_at, "payload": item.payload}
            for item in store.list_deployments(node_id=node_id)
        ]
    }


@app.post("/api/v1/reid/events")
@app.post("/reid/events")
def ingest_reid_event(request: ReIDEventRequest) -> Dict[str, Any]:
    try:
        feature, crop_uri = decode_event_feature(request.event, PROJECT_ROOT, reid_extractor)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = reid_store.register_event(request.event, feature, crop_uri, feature_source="http_event")
    return {"item": result}


@app.post("/api/v1/search/reid")
@app.post("/api/search/reid")
@app.post("/api/v1/reid/search/upload")
@app.post("/reid/search/upload")
async def search_reid_upload(
    file: UploadFile = File(...),
    top_k: int = 20,
) -> Dict[str, Any]:
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="uploaded image is empty")
    try:
        feature = reid_extractor.extract_from_bytes(image_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "query": {
            "filename": file.filename,
            "feature_version": feature.version,
            "feature_dimension": feature.dimension,
            "top_k": top_k,
        },
        "items": reid_store.search(feature, top_k=top_k),
    }


@app.post("/api/v1/reid/search/base64")
@app.post("/reid/search/base64")
def search_reid_base64(request: ReIDBase64SearchRequest) -> Dict[str, Any]:
    try:
        feature = reid_extractor.extract_from_base64(request.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64 image: {exc}") from exc
    return {
        "query": {
            "feature_version": feature.version,
            "feature_dimension": feature.dimension,
            "top_k": request.top_k,
        },
        "items": reid_store.search(feature, top_k=request.top_k),
    }


@app.get("/api/v1/reid/tracks/{global_id}")
@app.get("/reid/tracks/{global_id}")
def reid_track(global_id: str, limit: int = 200) -> Dict[str, Any]:
    return {"global_id": global_id, "items": reid_store.track(global_id, limit=limit)}


@app.get("/api/v1/reid/stats")
@app.get("/reid/stats")
def reid_stats() -> Dict[str, Any]:
    return reid_store.stats()


@app.post("/api/v1/reid/prune")
@app.post("/reid/prune")
def prune_reid_cache() -> Dict[str, Any]:
    return {"deleted": reid_store.prune_expired(), "stats": reid_store.stats()}


# ==================== 任务十二新增路由（你的核心产出） ====================

@app.post("/api/v1/nodes/register")
def register_node(payload: NodeRegister, db: Session = Depends(get_db)):
    """Savant 容器启动时调用，上报自己的 GPU 和 HTTP 接口"""
    node = db.query(Node).filter(Node.node_id == payload.node_id).first()
    if node:
        node.gpu_id = payload.gpu_id
        node.api_endpoint = payload.api_endpoint
        node.max_streams = payload.max_streams
        node.status = "idle"
        node.last_heartbeat = datetime.utcnow()
    else:
        node = Node(
            node_id=payload.node_id,
            gpu_id=payload.gpu_id,
            api_endpoint=payload.api_endpoint,
            max_streams=payload.max_streams,
            last_heartbeat=datetime.utcnow(),
        )
        db.add(node)
    db.commit()
    return {"status": "registered", "node_id": payload.node_id}


@app.get("/api/v1/nodes")
def list_nodes(db: Session = Depends(get_db)):
    """查询所有 Savant 节点状态，用于负载均衡调度"""
    nodes = db.query(Node).all()
    return [{
        "node_id": n.node_id,
        "gpu_id": n.gpu_id,
        "api_endpoint": n.api_endpoint,
        "status": n.status,
        "max_streams": n.max_streams,
        "assigned_cameras": json.loads(n.assigned_cameras or "[]"),
        "last_heartbeat": n.last_heartbeat.isoformat() if n.last_heartbeat else None,
    } for n in nodes]


@app.post("/api/v1/nodes/{node_id}/heartbeat")
def node_heartbeat(node_id: str, db: Session = Depends(get_db)):
    """Savant 节点定期心跳"""
    node = db.query(Node).filter(Node.node_id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    node.last_heartbeat = datetime.utcnow()
    db.commit()
    return {"status": "ok", "node_id": node_id}


@app.post("/api/v1/cameras")
def create_camera(cam_id: str, src_url: str, node_id: Optional[str] = None,
                  db: Session = Depends(get_db)):
    """注册摄像头；如果指定 node_id，自动分配节点"""
    if db.query(Camera).filter(Camera.cam_id == cam_id).first():
        raise HTTPException(409, "Camera already exists")
    cam = Camera(cam_id=cam_id, src_url=src_url, assigned_node_id=node_id)
    db.add(cam)
    if node_id:
        node = db.query(Node).filter(Node.node_id == node_id).first()
        if node:
            assigned = json.loads(node.assigned_cameras or "[]")
            if cam_id not in assigned:
                assigned.append(cam_id)
                node.assigned_cameras = json.dumps(assigned)
    db.commit()
    return {"status": "created", "cam_id": cam_id, "assigned_node_id": node_id}


@app.get("/api/v1/cameras/{cam_id}/config", response_model=CameraConfigOut)
def get_camera_config(cam_id: str, db: Session = Depends(get_db)):
    """Savant 节点启动时拉取完整配置"""
    cam = db.query(Camera).filter(Camera.cam_id == cam_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    rois = [{"name": r.name, "type": r.type, "points": json.loads(r.points_json)}
            for r in db.query(ROI).filter(ROI.cam_id == cam_id).all()]
    rules = [{"rule_type": r.rule_type, "params": json.loads(r.params_json)}
             for r in db.query(Rule).filter(Rule.cam_id == cam_id).all()]
    return CameraConfigOut(
        cam_id=cam.cam_id, src_url=cam.src_url, enabled=cam.enabled,
        assigned_node_id=cam.assigned_node_id,
        current_model_id=cam.current_model_id,
        infer_fps=cam.infer_fps, motion_threshold=cam.motion_threshold,
        motion_mask=cam.motion_mask, privacy_mask=cam.privacy_mask,
        permission_level=cam.permission_level,
        rois=rois, rules=rules,
    )


@app.get("/api/v1/cameras")
def list_cameras(db: Session = Depends(get_db)):
    cams = db.query(Camera).all()
    return [{
        "cam_id": c.cam_id, "enabled": c.enabled,
        "assigned_node_id": c.assigned_node_id,
        "current_model_id": c.current_model_id,
    } for c in cams]


@app.post("/api/v1/models/register")
def register_model(payload: ModelRegister, db: Session = Depends(get_db)):
    """注册模型到模型库（如白天模型、晚上模型）"""
    if db.query(Model).filter(Model.model_id == payload.model_id).first():
        raise HTTPException(409, "Model already exists")
    m = Model(
        model_id=payload.model_id, name=payload.name,
        engine_path=payload.engine_path,
        config_patch=json.dumps(payload.config_patch) if payload.config_patch else None,
        description=payload.description,
    )
    db.add(m)
    db.commit()
    return {"status": "registered", "model_id": payload.model_id}


@app.get("/api/v1/models")
def list_models(db: Session = Depends(get_db)):
    models = db.query(Model).all()
    return [{
        "model_id": m.model_id, "name": m.name,
        "engine_path": m.engine_path, "description": m.description,
    } for m in models]


@app.post("/api/v1/models/{model_id}/switch")
def switch_model(model_id: str, req: SwitchModelRequest, db: Session = Depends(get_db)):
    """
    热切换模型。
    - target_cam_id=null：全局切换
    - target_cam_id=具体值：单路切换
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if not model:
        raise HTTPException(404, "Model not found")
    if req.target_cam_id:
        cam = db.query(Camera).filter(Camera.cam_id == req.target_cam_id).first()
        if not cam:
            raise HTTPException(404, "Camera not found")
        cam.current_model_id = model_id
        target_nodes = [cam.assigned_node_id] if cam.assigned_node_id else []
    else:
        db.query(Camera).update({Camera.current_model_id: model_id})
        target_nodes = [n.node_id for n in db.query(Node).all()]
    db.commit()

    results = []
    config_patch = json.loads(model.config_patch) if model.config_patch else {}
    for node_id in target_nodes:
        node = db.query(Node).filter(Node.node_id == node_id).first()
        if node and node.api_endpoint:
            res = sync_agent.send_model_switch(
                node.api_endpoint, model_id=model_id,
                engine_path=model.engine_path,
                config_patch=config_patch,
                cam_id=req.target_cam_id,
            )
            results.append({"node_id": node_id, "result": res})
    return {
        "status": "switch_issued", "model_id": model_id,
        "target": req.target_cam_id or "ALL",
        "affected_nodes": results,
    }


@app.put("/api/v1/cameras/{cam_id}/roi")
def update_rois(cam_id: str, rois: List[ROIUpdate], db: Session = Depends(get_db)):
    """保存 ROI 多边形；前端 Canvas 绘制后调用"""
    cam = db.query(Camera).filter(Camera.cam_id == cam_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    db.query(ROI).filter(ROI.cam_id == cam_id).delete()
    for r in rois:
        db.add(ROI(
            roi_id=str(uuid.uuid4())[:8], cam_id=cam_id,
            name=r.name, type=r.type, points_json=json.dumps(r.points),
        ))
    db.commit()
    version_id = create_snapshot(db, cam_id, created_by="api_roi_update")
    sync_agent.notify_config_reload(cam_id, target_node_id=cam.assigned_node_id)
    return {"status": "ok", "cam_id": cam_id, "roi_count": len(rois), "version_id": version_id}


@app.put("/api/v1/cameras/{cam_id}/rules")
def update_rules(cam_id: str, rules: List[RuleUpdate], db: Session = Depends(get_db)):
    """保存区域规则（绊线、滞留、密度）"""
    cam = db.query(Camera).filter(Camera.cam_id == cam_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    db.query(Rule).filter(Rule.cam_id == cam_id).delete()
    for r in rules:
        db.add(Rule(
            rule_id=str(uuid.uuid4())[:8], cam_id=cam_id,
            rule_type=r.rule_type, params_json=json.dumps(r.params),
        ))
    db.commit()
    version_id = create_snapshot(db, cam_id, created_by="api_rule_update")
    sync_agent.notify_config_reload(cam_id, target_node_id=cam.assigned_node_id)
    return {"status": "ok", "cam_id": cam_id, "rule_count": len(rules), "version_id": version_id}


@app.get("/api/v1/cameras/{cam_id}/versions")
def list_versions(cam_id: str, db: Session = Depends(get_db)):
    """查询某摄像头的所有历史版本"""
    versions = db.query(ConfigVersion).filter(
        ConfigVersion.cam_id == cam_id
    ).order_by(ConfigVersion.created_at.desc()).all()
    return [{
        "version_id": v.version_id, "cam_id": v.cam_id,
        "created_by": v.created_by, "created_at": v.created_at.isoformat(),
        "snapshot_preview": json.loads(v.snapshot_json) if v.snapshot_json else {},
    } for v in versions]


@app.post("/api/v1/cameras/{cam_id}/rollback")
def rollback_camera(cam_id: str, version_id: str, db: Session = Depends(get_db)):
    """回滚到指定版本，并通知 Savant 节点重载"""
    result = rollback(db, cam_id, version_id)
    cam = db.query(Camera).filter(Camera.cam_id == cam_id).first()
    sync_agent.notify_config_reload(cam_id, target_node_id=cam.assigned_node_id if cam else None)
    return result


@app.post("/api/v1/config/broadcast")
def broadcast_config_reload(db: Session = Depends(get_db)):
    """一键通知所有节点重载配置"""
    nodes = db.query(Node).all()
    results = []
    for node in nodes:
        res = sync_agent.broadcast_command({
            "command_type": "CONFIG_RELOAD",
            "timestamp": time.time(),
        })
        results.append({"node_id": node.node_id, "result": res})
    return {"status": "broadcasted", "node_count": len(results), "results": results}


# ==================== 工具函数（原有） ====================

def record_to_json(record: Any) -> str:
    return json.dumps(
        {"id": record.id, "created_at": record.created_at, "payload": record.payload},
        ensure_ascii=False,
        indent=2,
    )