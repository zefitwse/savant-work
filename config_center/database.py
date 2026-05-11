"""
config_center/database.py
任务十二：配置中心数据库模型
与 savant-work 项目集成，使用 SQLite + SQLAlchemy
"""
from sqlalchemy import create_engine, Column, String, Integer, Boolean, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import json

Base = declarative_base()

class Camera(Base):
    __tablename__ = "cameras"
    cam_id = Column(String, primary_key=True)
    src_url = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    assigned_node_id = Column(String, ForeignKey("nodes.node_id"))
    current_model_id = Column(String, ForeignKey("models.model_id"))
    infer_fps = Column(Integer, default=5)
    motion_threshold = Column(Integer, default=50000)   # 任务七：运动阈值
    motion_mask = Column(Boolean, default=True)
    privacy_mask = Column(Boolean, default=True)
    permission_level = Column(String, default="user")   # admin / user
    created_at = Column(DateTime, default=datetime.utcnow)

    rois = relationship("ROI", back_populates="camera", cascade="all, delete-orphan")
    rules = relationship("Rule", back_populates="camera", cascade="all, delete-orphan")

class Model(Base):
    __tablename__ = "models"
    model_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    engine_path = Column(String, nullable=False)        # Savant 容器内路径，如 /models/yolov8n.engine
    config_patch = Column(Text)                         # JSON：覆盖 module.yml 的参数
    description = Column(Text)
    active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Node(Base):
    __tablename__ = "nodes"
    node_id = Column(String, primary_key=True)            # 如 savant-gpu-001
    gpu_id = Column(Integer, nullable=False)
    api_endpoint = Column(String, nullable=False)           # Savant 节点 HTTP 接口
    status = Column(String, default="idle")             # idle / busy / offline
    max_streams = Column(Integer, default=10)
    assigned_cameras = Column(Text, default="[]")         # JSON: ["cam_001"]
    last_heartbeat = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class ROI(Base):
    __tablename__ = "rois"
    roi_id = Column(String, primary_key=True)
    cam_id = Column(String, ForeignKey("cameras.cam_id", ondelete="CASCADE"))
    name = Column(String, nullable=False)
    type = Column(String, CheckConstraint("type IN ('forbidden', 'warning')"))
    points_json = Column(Text, nullable=False)            # [[x,y], [x,y], ...]
    created_at = Column(DateTime, default=datetime.utcnow)
    camera = relationship("Camera", back_populates="rois")

class Rule(Base):
    __tablename__ = "rules"
    rule_id = Column(String, primary_key=True)
    cam_id = Column(String, ForeignKey("cameras.cam_id", ondelete="CASCADE"))
    rule_type = Column(String, CheckConstraint("rule_type IN ('tripwire', 'loitering', 'density')"))
    params_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    camera = relationship("Camera", back_populates="rules")

class ConfigVersion(Base):
    __tablename__ = "config_versions"
    version_id = Column(String, primary_key=True)
    cam_id = Column(String, ForeignKey("cameras.cam_id"))
    snapshot_json = Column(Text, nullable=False)
    created_by = Column(String, default="system")
    created_at = Column(DateTime, default=datetime.utcnow)

# 初始化引擎（SQLite 文件放在项目根目录，便于 Docker 挂载）
import os
_db_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runtime"))
os.makedirs(_db_dir, exist_ok=True)
engine = create_engine(f"sqlite:///{_db_dir}/config_center.db", echo=False)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
