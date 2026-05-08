from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = Path("runtime/edge_control.db")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class StoredRecord:
    id: int
    payload: Dict[str, Any]
    created_at: str


class ControlStore:
    """SQLite-backed control plane store used by edge nodes and the API."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def save_model_switch(
        self,
        node_id: str,
        detector: str,
        engine_path: str,
        labels_path: Optional[str],
        reason: str,
    ) -> StoredRecord:
        payload = {
            "node_id": node_id,
            "detector": detector,
            "engine_path": engine_path,
            "labels_path": labels_path,
            "reason": reason,
            "status": "pending_apply",
        }
        return self._insert("model_switches", payload)

    def latest_model_switch(self, node_id: Optional[str] = None) -> Optional[StoredRecord]:
        if node_id:
            return self._select_latest("model_switches", "json_extract(payload, '$.node_id') = ?", [node_id])
        return self._select_latest("model_switches")

    def save_camera_config(
        self,
        camera_id: str,
        version: str,
        roi: List[Dict[str, Any]],
        thresholds: Dict[str, float],
        algorithm_params: Dict[str, Any],
        privacy: Dict[str, Any],
    ) -> StoredRecord:
        payload = {
            "camera_id": camera_id,
            "version": version,
            "roi": roi,
            "thresholds": thresholds,
            "algorithm_params": algorithm_params,
            "privacy": privacy,
        }
        return self._insert("camera_configs", payload)

    def latest_camera_config(self, camera_id: str) -> Optional[StoredRecord]:
        return self._select_latest(
            "camera_configs",
            "json_extract(payload, '$.camera_id') = ?",
            [camera_id],
        )

    def save_deployment(
        self,
        node_id: str,
        camera_ids: List[str],
        config_version: Optional[str],
    ) -> StoredRecord:
        payload = {
            "node_id": node_id,
            "camera_ids": camera_ids,
            "config_version": config_version,
            "status": "pending_apply",
        }
        return self._insert("deployments", payload)

    def list_deployments(self, node_id: Optional[str] = None) -> List[StoredRecord]:
        if node_id:
            return self._select_many("deployments", "json_extract(payload, '$.node_id') = ?", [node_id])
        return self._select_many("deployments")

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_switches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS camera_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deployments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _insert(self, table: str, payload: Dict[str, Any]) -> StoredRecord:
        created_at = utc_now_iso()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"INSERT INTO {table} (payload, created_at) VALUES (?, ?)",
                [json.dumps(payload, ensure_ascii=False), created_at],
            )
            record_id = int(cursor.lastrowid)
        return StoredRecord(record_id, payload, created_at)

    def _select_latest(
        self,
        table: str,
        where: Optional[str] = None,
        params: Optional[List[Any]] = None,
    ) -> Optional[StoredRecord]:
        records = self._select_many(table, where, params, limit=1)
        return records[0] if records else None

    def _select_many(
        self,
        table: str,
        where: Optional[str] = None,
        params: Optional[List[Any]] = None,
        limit: Optional[int] = None,
    ) -> List[StoredRecord]:
        sql = f"SELECT id, payload, created_at FROM {table}"
        values: List[Any] = params or []
        if where:
            sql += f" WHERE {where}"
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ?"
            values.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, values).fetchall()
        return [
            StoredRecord(int(row[0]), json.loads(row[1]), str(row[2]))
            for row in rows
        ]
