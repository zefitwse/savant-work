from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class EventObject:
    camera_id: str
    object_id: int
    class_id: int
    class_name: str
    confidence: float
    bbox: Mapping[str, float]
    attributes: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)

    def to_event(self, event_type: str) -> Dict[str, Any]:
        return {
            "event_type": event_type,
            "camera_id": self.camera_id,
            "object_id": self.object_id,
            "track_id": self.object_id,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "bbox": {
                "left": round(float(self.bbox["left"]), 2),
                "top": round(float(self.bbox["top"]), 2),
                "width": round(float(self.bbox["width"]), 2),
                "height": round(float(self.bbox["height"]), 2),
            },
            "attributes": self.attributes,
            "timestamp": self.timestamp,
        }


class SparseEventBuilder:
    """Turns tracked per-frame metadata into sparse Kafka-friendly events.

    Savant integration note:
    - Call ``update`` from a frame processor after tracker metadata is available.
    - Pass PGIE objects only; SGIE results should already be folded into attributes.
    """

    def __init__(self, ttl_frames: int = 90, attribute_cooldown_frames: int = 30) -> None:
        self.ttl_frames = ttl_frames
        self.attribute_cooldown_frames = attribute_cooldown_frames
        self._states: Dict[str, Dict[str, Any]] = {}

    def update(self, frame_num: int, objects: List[EventObject]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        seen = set()

        for obj in objects:
            key = f"{obj.camera_id}:{obj.object_id}"
            seen.add(key)
            semantic_attrs = self._semantic_attrs(obj.attributes)
            state = self._states.get(key)
            if state is None:
                self._states[key] = {
                    "object": obj,
                    "attrs": semantic_attrs,
                    "last_seen": frame_num,
                    "last_attribute_emit": frame_num,
                }
                events.append(obj.to_event("object_entered"))
                continue

            merged_attributes = dict(state["object"].attributes)
            merged_attributes.update(obj.attributes)
            obj.attributes = merged_attributes
            semantic_attrs = self._semantic_attrs(obj.attributes)
            if (
                semantic_attrs != state["attrs"]
                and frame_num - int(state["last_attribute_emit"]) >= self.attribute_cooldown_frames
            ):
                events.append(obj.to_event("attribute_changed"))
                state["last_attribute_emit"] = frame_num

            state["object"] = obj
            state["attrs"] = semantic_attrs
            state["last_seen"] = frame_num

        for key, state in list(self._states.items()):
            if key in seen:
                continue
            if frame_num - int(state["last_seen"]) >= self.ttl_frames:
                events.append(state["object"].to_event("object_expired"))
                del self._states[key]

        return events

    @staticmethod
    def _semantic_attrs(attributes: Mapping[str, Any]) -> Dict[str, Any]:
        volatile_attrs = {
            "crop_uri",
            "crop_status",
            "gpu_memory_ref",
        }
        return {
            key: value
            for key, value in attributes.items()
            if not key.endswith("_confidence")
            and key not in volatile_attrs
        }


def fold_secondary_attributes(
    primary_objects: List[EventObject],
    secondary_objects: List[EventObject],
    label_map: Optional[Dict[str, str]] = None,
) -> List[EventObject]:
    """Associate SGIE detections with PGIE objects by bbox center point."""
    label_map = label_map or {
        "hardhat": "helmet",
        "no-hardhat": "helmet",
        "vest": "workwear",
        "no-vest": "workwear",
    }

    for secondary in secondary_objects:
        parent = _find_parent(primary_objects, secondary)
        if parent is None:
            continue
        attr_key = label_map.get(secondary.class_name)
        if attr_key is None:
            continue
        prev_conf = float(parent.attributes.get(f"{attr_key}_confidence", -1.0))
        if secondary.confidence >= prev_conf:
            parent.attributes[attr_key] = secondary.class_name
            parent.attributes[f"{attr_key}_confidence"] = round(float(secondary.confidence), 4)

    return primary_objects


def _find_parent(primary_objects: List[EventObject], secondary: EventObject) -> Optional[EventObject]:
    center_x = float(secondary.bbox["left"]) + float(secondary.bbox["width"]) / 2.0
    center_y = float(secondary.bbox["top"]) + float(secondary.bbox["height"]) / 2.0

    for primary in primary_objects:
        left = float(primary.bbox["left"])
        top = float(primary.bbox["top"])
        right = left + float(primary.bbox["width"])
        bottom = top + float(primary.bbox["height"])
        if left <= center_x <= right and top <= center_y <= bottom:
            return primary
    return None
