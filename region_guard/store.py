# task6/store.py
import json
import sqlite3
import time
import uuid
from typing import Optional


class AlertStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def connect(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task6_alerts (
                    id TEXT PRIMARY KEY,
                    camera_id TEXT,
                    track_id TEXT,
                    alert_type TEXT,
                    roi_names TEXT,
                    bbox TEXT,
                    status TEXT,
                    message TEXT,
                    created_at REAL
                )
                """
            )
            conn.commit()

    def save_alert(
        self,
        camera_id: str,
        track_id: str,
        alert_type: str,
        roi_names: list[str],
        bbox,
        message: str,
    ) -> dict:
        alert = {
            "id": str(uuid.uuid4()),
            "camera_id": camera_id,
            "track_id": str(track_id),
            "alert_type": alert_type,
            "roi_names": roi_names,
            "bbox": bbox,
            "status": "open",
            "message": message,
            "created_at": time.time(),
        }

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task6_alerts
                (id, camera_id, track_id, alert_type, roi_names, bbox, status, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert["id"],
                    alert["camera_id"],
                    alert["track_id"],
                    alert["alert_type"],
                    json.dumps(alert["roi_names"], ensure_ascii=False),
                    json.dumps(alert["bbox"], ensure_ascii=False),
                    alert["status"],
                    alert["message"],
                    alert["created_at"],
                ),
            )
            conn.commit()

        return alert

    def list_alerts(
        self,
        camera_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT id, camera_id, track_id, alert_type, roi_names, bbox, status, message, created_at FROM task6_alerts"
        params = []

        if camera_id:
            sql += " WHERE camera_id = ?"
            params.append(camera_id)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        result = []
        for row in rows:
            result.append(
                {
                    "id": row[0],
                    "camera_id": row[1],
                    "track_id": row[2],
                    "alert_type": row[3],
                    "roi_names": json.loads(row[4]),
                    "bbox": json.loads(row[5]),
                    "status": row[6],
                    "message": row[7],
                    "created_at": row[8],
                }
            )
        return result