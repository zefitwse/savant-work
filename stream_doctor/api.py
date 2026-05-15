import json
import sqlite3

from fastapi import FastAPI

from stream_doctor.config import DB_PATH
from stream_doctor.store import VQDStore

app = FastAPI(title="StreamDoctor VQD API")

# Ensure DB/table exist even if worker has not run yet.
VQDStore(DB_PATH)


def get_latest_event(camera_id: str = "cam01"):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, camera_id, status, issues, metrics, message, created_at
            FROM task9_vqd_events
            WHERE camera_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (camera_id,),
        )

        row = cursor.fetchone()
        conn.close()
    except sqlite3.Error as exc:
        return {
            "msg_version": "1.0",
            "stream_id": camera_id,
            "camera_id": camera_id,
            "status": "UNKNOWN",
            "issues": ["DB_ERROR"],
            "message": f"视频质量诊断存储不可用: {exc}",
        }

    if not row:
        return {
            "msg_version": "1.0",
            "stream_id": camera_id,
            "camera_id": camera_id,
            "status": "UNKNOWN",
            "issues": [],
            "message": "暂无视频质量诊断数据",
        }

    return {
        "id": row[0],
        "msg_version": "1.0",
        "stream_id": row[1],
        "camera_id": row[1],
        "status": row[2],
        "issues": json.loads(row[3]),
        "metrics": json.loads(row[4]),
        "message": row[5],
        "created_at": row[6],
    }


@app.get("/api/v1/vqd/status")
def vqd_status(camera_id: str = "cam01"):
    return get_latest_event(camera_id)


@app.get("/api/v1/vqd/events")
def vqd_events(camera_id: str = "cam01", limit: int = 20):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, camera_id, status, issues, metrics, message, created_at
            FROM task9_vqd_events
            WHERE camera_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (camera_id, limit),
        )

        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error:
        rows = []

    return {
        "items": [
            {
                "id": row[0],
                "msg_version": "1.0",
                "stream_id": row[1],
                "camera_id": row[1],
                "status": row[2],
                "issues": json.loads(row[3]),
                "metrics": json.loads(row[4]),
                "message": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]
    }
