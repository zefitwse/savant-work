from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


BBox = Tuple[int, int, int, int]


@dataclass
class PrivacyPolicy:
    enabled: bool = True
    masked_roles: List[str] = field(default_factory=lambda: ["operator", "guest"])
    mosaic_block_size: int = 18
    sensitive_classes: List[str] = field(default_factory=lambda: ["face", "license_plate"])
    static_regions: List[BBox] = field(default_factory=list)


class PrivacyMasker:
    """Applies mosaic masks for preview while preserving original metadata.

    Savant integration note:
    - Run this processor only on the preview branch.
    - Kafka events must use the original detection bbox values before masking.
    - Administrators should be routed to the raw stream branch instead.
    """

    def __init__(self, policy: Optional[PrivacyPolicy] = None) -> None:
        self.policy = policy or PrivacyPolicy()

    def should_mask(self, role: str) -> bool:
        return self.policy.enabled and role.lower() in self.policy.masked_roles

    def collect_mask_boxes(self, detections: Iterable[Dict[str, object]]) -> List[BBox]:
        boxes: List[BBox] = list(self.policy.static_regions)
        for detection in detections:
            class_name = str(detection.get("class_name", ""))
            if class_name not in self.policy.sensitive_classes:
                continue
            bbox = detection.get("bbox", {})
            if not isinstance(bbox, dict):
                continue
            left = int(float(bbox.get("left", 0)))
            top = int(float(bbox.get("top", 0)))
            width = int(float(bbox.get("width", 0)))
            height = int(float(bbox.get("height", 0)))
            boxes.append((left, top, width, height))
        return boxes

    def collect_preview_mask_boxes(self, objects: Iterable[Any]) -> List[BBox]:
        """Collect preview-only mask boxes from Savant object metadata.

        The coursework model currently has no dedicated face detector. For a
        demonstrable privacy preview, person objects contribute an estimated
        head/face region while real face/license_plate objects can be masked
        directly when those models are added later.
        """
        boxes: List[BBox] = list(self.policy.static_regions)
        for obj_meta in objects:
            label = str(getattr(obj_meta, "label", ""))
            bbox = getattr(obj_meta, "bbox", None)
            if bbox is None:
                continue
            if label == "person":
                boxes.append(self.estimate_person_head_box(bbox))
                continue
            if label in self.policy.sensitive_classes:
                boxes.append(self._bbox_to_ltwh(bbox))
        return [box for box in boxes if box[2] > 0 and box[3] > 0]

    @staticmethod
    def estimate_person_head_box(bbox: Any) -> BBox:
        left, top, width, height = PrivacyMasker._bbox_to_ltwh(bbox)
        # Use a deliberately generous head/upper-body region for moving people.
        # This is safer than a tight face proxy when no face detector is present.
        head_width = max(1, int(width * 0.7))
        head_height = max(1, int(height * 0.36))
        head_left = int(left + (width - head_width) / 2)
        head_top = int(top)
        return head_left, head_top, head_width, head_height

    @staticmethod
    def _bbox_to_ltwh(bbox: Any) -> BBox:
        left = float(getattr(bbox, "left", 0.0))
        top = float(getattr(bbox, "top", 0.0))
        if left == 0.0 and top == 0.0 and hasattr(bbox, "xc"):
            left = float(bbox.xc - bbox.width / 2.0)
            top = float(bbox.yc - bbox.height / 2.0)
        return (
            int(left),
            int(top),
            int(float(getattr(bbox, "width", 0.0))),
            int(float(getattr(bbox, "height", 0.0))),
        )

    def apply_numpy(self, frame: object, boxes: Iterable[BBox]) -> object:
        """Apply mosaic to a numpy frame when OpenCV/numpy are available."""
        try:
            import cv2
        except ImportError:
            return frame

        height, width = frame.shape[:2]
        for left, top, box_width, box_height in boxes:
            x1 = max(0, left)
            y1 = max(0, top)
            x2 = min(width, left + box_width)
            y2 = min(height, top + box_height)
            if x2 <= x1 or y2 <= y1:
                continue
            roi = frame[y1:y2, x1:x2]
            small_width = max(1, int((x2 - x1) / self.policy.mosaic_block_size))
            small_height = max(1, int((y2 - y1) / self.policy.mosaic_block_size))
            mosaic = cv2.resize(roi, (small_width, small_height), interpolation=cv2.INTER_LINEAR)
            frame[y1:y2, x1:x2] = cv2.resize(mosaic, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
        return frame
