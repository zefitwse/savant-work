from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from coursework_savant.reid import ReIDFeatureExtractor, ReIDSQLiteStore, decode_event_feature
from coursework_savant.telemetry import instrument_fastapi

try:
    from .control_store import ControlStore
except ImportError:  # allows running as `python src/control_api.py` in local tests
    from control_store import ControlStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
MODEL_STATE_PATH = RUNTIME_DIR / "model_state.json"

app = FastAPI(title="DeepStream/Savant Edge Control API", version="0.1.0")
instrument_fastapi(app)
store = ControlStore(PROJECT_ROOT / "runtime" / "edge_control.db")
reid_model_path = os.getenv("REID_MODEL_PATH")
reid_extractor = ReIDFeatureExtractor(model_path=Path(reid_model_path) if reid_model_path else None)
reid_store = ReIDSQLiteStore(PROJECT_ROOT / "runtime" / "edge_control.db")


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


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


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
    engine_path = Path(request.engine_path)
    if not request.engine_path.endswith(".engine"):
        raise HTTPException(status_code=400, detail="engine_path must point to a .engine file.")

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
    return {
        "id": record.id,
        "created_at": record.created_at,
        "payload": record.payload,
        "apply_mode": "savant_runtime_watches_runtime_model_state",
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


def record_to_json(record: Any) -> str:
    import json

    return json.dumps(
        {"id": record.id, "created_at": record.created_at, "payload": record.payload},
        ensure_ascii=False,
        indent=2,
    )
