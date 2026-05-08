from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np


DEFAULT_TTL_SECONDS = 3600
DEFAULT_MATCH_THRESHOLD = 0.84
DEFAULT_TOP_K = 20


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(a, b) / denominator)


@dataclass(frozen=True)
class ReIDFeature:
    vector: List[float]
    version: str
    dimension: int


@dataclass(frozen=True)
class ReIDRecord:
    id: int
    global_id: str
    stream_id: str
    track_id: str
    crop_uri: str
    feature_version: str
    timestamp: str
    similarity: Optional[float]
    event: Dict[str, Any]
    feature: List[float]


class ReIDFeatureExtractor:
    """Extracts a stable Re-ID embedding from target crops.

    When ``model_path`` points to an ONNX Re-ID model, the extractor runs the
    model on CPU and uses its first output as the embedding. The histogram
    fallback keeps local interface tests working when model weights are not
    present on the current machine.
    """

    def __init__(self, image_size: Tuple[int, int] = (64, 128), model_path: Optional[Path] = None) -> None:
        self.image_size = image_size
        self.model_path = Path(model_path) if model_path else None
        self.session: Any = None
        self.input_name: Optional[str] = None
        self.feature_version = "reid-color-grid-v1"
        if self.model_path is not None:
            self._load_onnx_model(self.model_path)

    def extract_from_path(self, image_path: Path) -> ReIDFeature:
        return self.extract_from_bytes(image_path.read_bytes())

    def extract_from_base64(self, image_base64: str) -> ReIDFeature:
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]
        return self.extract_from_bytes(base64.b64decode(image_base64))

    def extract_from_bytes(self, image_bytes: bytes) -> ReIDFeature:
        image = self._decode_rgb(image_bytes)
        vector = self._extract_model_embedding(image) if self.session is not None else self._extract_color_grid_embedding(image)
        return ReIDFeature(vector=vector, version=self.feature_version, dimension=len(vector))

    def _load_onnx_model(self, model_path: Path) -> None:
        if not model_path.exists():
            raise FileNotFoundError(f"Re-ID ONNX model does not exist: {model_path}")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime is required when REID_MODEL_PATH is configured.") from exc

        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.feature_version = f"onnx-{model_path.stem}"

    def _decode_rgb(self, image_bytes: bytes) -> np.ndarray:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Pillow is required for Re-ID image decoding.") from exc

        import io

        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB").resize(self.image_size)
            return np.asarray(img, dtype=np.uint8)

    def _extract_model_embedding(self, image: np.ndarray) -> List[float]:
        if self.session is None or self.input_name is None:
            raise RuntimeError("Re-ID ONNX session is not initialized.")
        image_f = image.astype(np.float32) / 255.0
        mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        tensor = ((image_f - mean) / std).transpose(2, 0, 1)[None, :, :, :].astype(np.float32)
        output = self.session.run(None, {self.input_name: tensor})[0]
        vector = np.asarray(output, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm > 0.0:
            vector = vector / norm
        return [round(float(value), 6) for value in vector.tolist()]

    @staticmethod
    def _extract_color_grid_embedding(image: np.ndarray) -> List[float]:
        image_f = image.astype(np.float32) / 255.0
        height, width = image_f.shape[:2]
        features: List[float] = []

        # Global RGB histograms describe clothing/color appearance.
        for channel in range(3):
            hist, _ = np.histogram(image_f[:, :, channel], bins=16, range=(0.0, 1.0), density=False)
            features.extend(hist.astype(np.float32).tolist())

        # A coarse spatial grid gives the vector some Re-ID-like layout signal.
        for gy in range(4):
            for gx in range(2):
                y0 = math.floor(height * gy / 4)
                y1 = math.floor(height * (gy + 1) / 4)
                x0 = math.floor(width * gx / 2)
                x1 = math.floor(width * (gx + 1) / 2)
                patch = image_f[y0:y1, x0:x1]
                features.extend(patch.mean(axis=(0, 1)).tolist())
                features.extend(patch.std(axis=(0, 1)).tolist())

        # Shape/texture summary helps distinguish crops with similar colors.
        gray = image_f.mean(axis=2)
        grad_y = np.abs(np.diff(gray, axis=0)).mean() if gray.shape[0] > 1 else 0.0
        grad_x = np.abs(np.diff(gray, axis=1)).mean() if gray.shape[1] > 1 else 0.0
        features.extend([float(gray.mean()), float(gray.std()), float(grad_x), float(grad_y)])

        vector = np.asarray(features, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm > 0.0:
            vector = vector / norm
        return [round(float(value), 6) for value in vector.tolist()]


class ReIDSQLiteStore:
    """One-hour Re-ID feature cache and cross-camera global-id matcher."""

    def __init__(
        self,
        db_path: Path,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> None:
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self.match_threshold = match_threshold
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def register_event(
        self,
        event: Mapping[str, Any],
        feature: ReIDFeature,
        crop_uri: str,
        feature_source: str = "crop_uri",
    ) -> Dict[str, Any]:
        self.prune_expired()
        stream_id = event_stream_id(event)
        track_id = event_track_id(event)
        timestamp = str(event.get("timestamp") or utc_now_iso())

        existing_global_id = self._latest_global_id_for_track(stream_id, track_id)
        match = None if existing_global_id else self._best_cross_stream_match(stream_id, feature.vector)
        global_id = existing_global_id or (match.global_id if match else self._new_global_id(stream_id, track_id))
        similarity = 1.0 if existing_global_id else (match.similarity if match else None)

        payload = normalize_event_for_contract(event)
        payload["global_id"] = global_id
        payload["feature_version"] = feature.version
        payload["feature_source"] = feature_source
        payload["reid_similarity"] = similarity

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO reid_features (
                    global_id, stream_id, camera_id, track_id, crop_uri, feature_version,
                    feature_json, event_json, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    global_id,
                    stream_id,
                    stream_id,
                    track_id,
                    crop_uri,
                    feature.version,
                    json.dumps(feature.vector, separators=(",", ":")),
                    json.dumps(payload, ensure_ascii=False),
                    timestamp,
                    utc_now_iso(),
                ],
            )
            record_id = int(cursor.lastrowid)

        return {
            "msg_version": "1.0",
            "id": record_id,
            "event_type": "reid_matched" if match or existing_global_id else "reid_registered",
            "global_id": global_id,
            "stream_id": stream_id,
            "track_id": track_id,
            "crop_uri": crop_uri,
            "feature_version": feature.version,
            "feature_dimension": feature.dimension,
            "similarity": similarity,
            "matched_record_id": match.id if match else None,
            "matched_stream_id": match.stream_id if match else None,
            "matched_track_id": match.track_id if match else None,
            "timestamp": timestamp,
        }

    def search(self, feature: ReIDFeature, top_k: int = DEFAULT_TOP_K) -> List[Dict[str, Any]]:
        self.prune_expired()
        records = self._recent_records()
        scored = []
        for record in records:
            similarity = cosine_similarity(feature.vector, record.feature)
            scored.append((similarity, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [self._record_to_search_result(record, score) for score, record in scored[:top_k]]

    def track(self, global_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        self.prune_expired()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, global_id, stream_id, track_id, crop_uri, feature_version,
                       feature_json, event_json, timestamp
                FROM reid_features
                WHERE global_id = ?
                ORDER BY timestamp ASC, id ASC
                LIMIT ?
                """,
                [global_id, limit],
            ).fetchall()
        return [self._row_to_record(row, similarity=None).event for row in rows]

    def stats(self) -> Dict[str, Any]:
        self.prune_expired()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT global_id), COUNT(DISTINCT stream_id)
                FROM reid_features
                """
            ).fetchone()
        return {
            "ttl_seconds": self.ttl_seconds,
            "match_threshold": self.match_threshold,
            "feature_count": int(row[0] or 0),
            "global_id_count": int(row[1] or 0),
            "stream_count": int(row[2] or 0),
        }

    def prune_expired(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)).isoformat(timespec="milliseconds")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM reid_features WHERE timestamp < ?", [cutoff])
            return int(cursor.rowcount)

    def _best_cross_stream_match(self, stream_id: str, vector: Sequence[float]) -> Optional[ReIDRecord]:
        best: Optional[ReIDRecord] = None
        best_score = self.match_threshold
        for record in self._recent_records(exclude_stream_id=stream_id):
            score = cosine_similarity(vector, record.feature)
            if score >= best_score:
                best_score = score
                best = ReIDRecord(**{**record.__dict__, "similarity": score})
        return best

    def _latest_global_id_for_track(self, stream_id: str, track_id: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT global_id
                FROM reid_features
                WHERE stream_id = ? AND track_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                [stream_id, track_id],
            ).fetchone()
        return str(row[0]) if row else None

    def _recent_records(self, exclude_stream_id: Optional[str] = None) -> List[ReIDRecord]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.ttl_seconds)).isoformat(timespec="milliseconds")
        sql = """
            SELECT id, global_id, stream_id, track_id, crop_uri, feature_version,
                   feature_json, event_json, timestamp
            FROM reid_features
            WHERE timestamp >= ?
        """
        params: List[Any] = [cutoff]
        if exclude_stream_id:
            sql += " AND stream_id != ?"
            params.append(exclude_stream_id)
        sql += " ORDER BY timestamp DESC, id DESC"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(row, similarity=None) for row in rows]

    @staticmethod
    def _record_to_search_result(record: ReIDRecord, similarity: float) -> Dict[str, Any]:
        return {
            "id": record.id,
            "global_id": record.global_id,
            "stream_id": record.stream_id,
            "track_id": record.track_id,
            "crop_uri": record.crop_uri,
            "feature_version": record.feature_version,
            "timestamp": record.timestamp,
            "similarity": round(float(similarity), 6),
            "event": record.event,
        }

    @staticmethod
    def _row_to_record(row: Tuple[Any, ...], similarity: Optional[float]) -> ReIDRecord:
        return ReIDRecord(
            id=int(row[0]),
            global_id=str(row[1]),
            stream_id=str(row[2]),
            track_id=str(row[3]),
            crop_uri=str(row[4]),
            feature_version=str(row[5]),
            feature=json.loads(row[6]),
            event=json.loads(row[7]),
            timestamp=str(row[8]),
            similarity=similarity,
        )

    def _new_global_id(self, stream_id: str, track_id: str) -> str:
        digest = hashlib.sha1(f"{stream_id}:{track_id}:{uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:12]
        return f"gid-{digest}"

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reid_features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    global_id TEXT NOT NULL,
                    stream_id TEXT NOT NULL,
                    camera_id TEXT,
                    track_id TEXT NOT NULL,
                    crop_uri TEXT NOT NULL,
                    feature_version TEXT NOT NULL,
                    feature_json TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reid_features)").fetchall()}
            if "stream_id" not in columns:
                conn.execute("ALTER TABLE reid_features ADD COLUMN stream_id TEXT")
                if "camera_id" in columns:
                    conn.execute("UPDATE reid_features SET stream_id = camera_id WHERE stream_id IS NULL")
                else:
                    conn.execute("UPDATE reid_features SET stream_id = 'unknown' WHERE stream_id IS NULL")
            if "camera_id" not in columns:
                conn.execute("ALTER TABLE reid_features ADD COLUMN camera_id TEXT")
                conn.execute("UPDATE reid_features SET camera_id = stream_id WHERE camera_id IS NULL")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reid_features_track
                ON reid_features(stream_id, track_id, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reid_features_global
                ON reid_features(global_id, timestamp ASC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reid_features_timestamp
                ON reid_features(timestamp)
                """
            )


def resolve_crop_uri(project_root: Path, crop_uri: str) -> Path:
    path = Path(crop_uri)
    if path.is_absolute():
        return path
    parts = [part for part in crop_uri.replace("\\", "/").split("/") if part]
    return (project_root.joinpath(*parts)).resolve()


def event_stream_id(event: Mapping[str, Any]) -> str:
    return str(event.get("stream_id") or event.get("camera_id") or "unknown")


def event_track_id(event: Mapping[str, Any]) -> str:
    return str(event.get("track_id", event.get("object_id", "unknown")))


def event_bbox_xywh(event: Mapping[str, Any]) -> Optional[List[float]]:
    bbox_xywh = event.get("bbox_xywh")
    if isinstance(bbox_xywh, list) and len(bbox_xywh) == 4:
        return [round(float(value), 2) for value in bbox_xywh]

    bbox = event.get("bbox")
    if isinstance(bbox, Mapping):
        return [
            round(float(bbox.get("left", 0.0)), 2),
            round(float(bbox.get("top", 0.0)), 2),
            round(float(bbox.get("width", 0.0)), 2),
            round(float(bbox.get("height", 0.0)), 2),
        ]
    if isinstance(bbox, list) and len(bbox) == 4:
        return [round(float(value), 2) for value in bbox]
    return None


def normalize_event_for_contract(event: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = dict(event)
    normalized["msg_version"] = str(event.get("msg_version") or "1.0")
    normalized["stream_id"] = event_stream_id(event)
    normalized["track_id"] = event_track_id(event)

    class_name = event.get("class") or event.get("class_name")
    if class_name is not None:
        normalized["class"] = str(class_name)

    bbox_xywh = event_bbox_xywh(event)
    if bbox_xywh is not None:
        normalized["bbox_xywh"] = bbox_xywh

    attributes = event.get("attributes")
    if isinstance(attributes, Mapping):
        normalized["attributes"] = dict(attributes)
    return normalized


def decode_event_feature(event: Mapping[str, Any], project_root: Path, extractor: ReIDFeatureExtractor) -> Tuple[ReIDFeature, str]:
    attributes = event.get("attributes") or {}
    if not isinstance(attributes, Mapping):
        raise ValueError("event.attributes must be an object")
    crop_uri = str(attributes.get("crop_uri") or event.get("crop_uri") or "")
    if not crop_uri:
        raise ValueError("event must contain attributes.crop_uri")
    crop_path = resolve_crop_uri(project_root, crop_uri)
    if not crop_path.exists():
        raise FileNotFoundError(f"Re-ID crop does not exist: {crop_path}")
    return extractor.extract_from_path(crop_path), crop_uri
