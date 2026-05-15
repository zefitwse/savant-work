import json
import sqlite3
import time
import uuid


class VQDStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def connect(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task9_vqd_events (
                    id TEXT PRIMARY KEY,
                    camera_id TEXT,
                    status TEXT,
                    issues TEXT,
                    metrics TEXT,
                    message TEXT,
                    created_at REAL
                )
                """
            )
            conn.commit()

    def save_event(self, camera_id, status, issues, metrics, message):
        event = {
            "id": str(uuid.uuid4()),
            "camera_id": camera_id,
            "status": status,
            "issues": issues,
            "metrics": metrics,
            "message": message,
            "created_at": time.time(),
        }

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task9_vqd_events
                (id, camera_id, status, issues, metrics, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["camera_id"],
                    event["status"],
                    json.dumps(event["issues"], ensure_ascii=False),
                    json.dumps(event["metrics"], ensure_ascii=False),
                    event["message"],
                    event["created_at"],
                ),
            )
            conn.commit()

        return event