"""
config_center/version_manager.py
配置版本快照与回滚
"""
import json
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from config_center.database import Camera, ROI, Rule, ConfigVersion

def create_snapshot(db: Session, cam_id: str, created_by: str = "system") -> str:
    """为指定摄像头创建配置快照，返回 version_id"""
    cam = db.query(Camera).filter(Camera.cam_id == cam_id).first()
    if not cam:
        return None

    rois = [{"name": r.name, "type": r.type, "points": json.loads(r.points_json)}
            for r in db.query(ROI).filter(ROI.cam_id == cam_id).all()]
    rules = [{"rule_type": r.rule_type, "params": json.loads(r.params_json)}
             for r in db.query(Rule).filter(Rule.cam_id == cam_id).all()]

    snapshot = {
        "camera": {
            "src_url": cam.src_url,
            "enabled": cam.enabled,
            "assigned_node_id": cam.assigned_node_id,
            "current_model_id": cam.current_model_id,
            "infer_fps": cam.infer_fps,
            "motion_threshold": cam.motion_threshold,
            "motion_mask": cam.motion_mask,
            "privacy_mask": cam.privacy_mask,
            "permission_level": cam.permission_level,
        },
        "rois": rois,
        "rules": rules,
    }

    version_id = f"v_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{cam_id}"
    ver = ConfigVersion(
        version_id=version_id,
        cam_id=cam_id,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        created_by=created_by,
    )
    db.add(ver)
    db.commit()
    return version_id

def rollback(db: Session, cam_id: str, version_id: str) -> dict:
    """回滚到指定版本"""
    ver = db.query(ConfigVersion).filter(
        ConfigVersion.version_id == version_id,
        ConfigVersion.cam_id == cam_id
    ).first()
    if not ver:
        raise ValueError(f"Version {version_id} not found for {cam_id}")

    snap = json.loads(ver.snapshot_json)
    cam = db.query(Camera).filter(Camera.cam_id == cam_id).first()
    if not cam:
        raise ValueError(f"Camera {cam_id} not found")

    cfg = snap["camera"]
    cam.enabled = cfg["enabled"]
    cam.assigned_node_id = cfg.get("assigned_node_id")
    cam.current_model_id = cfg.get("current_model_id")
    cam.infer_fps = cfg["infer_fps"]
    cam.motion_threshold = cfg.get("motion_threshold", 50000)
    cam.motion_mask = cfg["motion_mask"]
    cam.privacy_mask = cfg["privacy_mask"]
    cam.permission_level = cfg["permission_level"]

    # 恢复 ROI
    db.query(ROI).filter(ROI.cam_id == cam_id).delete()
    for r in snap.get("rois", []):
        db.add(ROI(
            roi_id=str(uuid.uuid4())[:8],
            cam_id=cam_id,
            name=r["name"],
            type=r["type"],
            points_json=json.dumps(r["points"])
        ))

    # 恢复 Rules
    db.query(Rule).filter(Rule.cam_id == cam_id).delete()
    for r in snap.get("rules", []):
        db.add(Rule(
            rule_id=str(uuid.uuid4())[:8],
            cam_id=cam_id,
            rule_type=r["rule_type"],
            params_json=json.dumps(r["params"])
        ))

    db.commit()
    return {"status": "rollback_ok", "version_id": version_id, "cam_id": cam_id}
