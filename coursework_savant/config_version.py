from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import json


DB_PATH = Path("/workspace/deepstream_coursework/runtime/edge_control.db")


class VersionedConfigReader:
    """Read camera ROI, thresholds, algorithm parameters, and privacy policy."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    def latest_camera_config(self, camera_id: str) -> Optional[Dict[str, Any]]:
        if not self.db_path.exists():
            return None
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT payload
                FROM camera_configs
                WHERE json_extract(payload, '$.camera_id') = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                [camera_id],
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])
