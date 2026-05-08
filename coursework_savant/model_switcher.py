from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


MODEL_STATE_PATH = Path("/workspace/deepstream_coursework/runtime/model_state.json")


@dataclass(frozen=True)
class ModelSwitchCommand:
    id: int
    node_id: str
    detector: str
    engine_path: str
    labels_path: Optional[str]
    created_at: str


class ModelSwitchWatcher:
    """Small adapter for Savant hot-swap integration.

    The control API writes runtime/model_state.json. A Savant-specific wrapper can
    call ``poll`` and apply the returned command to its model manager when the id
    changes. This file intentionally does not restart the process.
    """

    def __init__(self, path: Path = MODEL_STATE_PATH) -> None:
        self.path = path
        self._last_id: Optional[int] = None

    def poll(self) -> Optional[ModelSwitchCommand]:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        command_id = int(data["id"])
        if command_id == self._last_id:
            return None
        payload = data["payload"]
        self._last_id = command_id
        return ModelSwitchCommand(
            id=command_id,
            node_id=str(payload["node_id"]),
            detector=str(payload["detector"]),
            engine_path=str(payload["engine_path"]),
            labels_path=payload.get("labels_path"),
            created_at=str(data["created_at"]),
        )
