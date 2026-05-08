from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from coursework_savant.event_builder import EventObject
from coursework_savant.telemetry import start_span


class TargetCropExporter:
    """Exports object crops for Re-ID consumers and annotates events.

    The exporter tries to read the current DeepStream/Savant frame from the
    Gst buffer. When the Python binding exposes a CUDA array interface, the
    device pointer is reported. Otherwise the event still carries a stable
    buffer reference that can be used for same-process debugging, while
    ``device_ptr`` remains null instead of pretending to be a CUDA pointer.
    """

    def __init__(
        self,
        output_dir: str = "/workspace/deepstream_coursework/runtime/crops",
        uri_prefix: str = "runtime/crops",
        enabled: bool = True,
        include_gpu_memory_ref: bool = True,
        write_crops: bool = True,
        max_crops_per_frame: int = 16,
        jpeg_quality: int = 90,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.uri_prefix = uri_prefix.strip("/\\")
        self.enabled = enabled
        self.include_gpu_memory_ref = include_gpu_memory_ref
        self.write_crops = write_crops
        self.max_crops_per_frame = max_crops_per_frame
        self.jpeg_quality = jpeg_quality

    def enrich(
        self,
        buffer: Any,
        frame_meta: Any,
        objects: Iterable[EventObject],
    ) -> None:
        if not self.enabled:
            return

        objects_list = [obj for obj in objects if obj.class_name == "person"]
        if not objects_list:
            return

        with start_span(
            "savant.reid.crop_export",
            {
                "camera_id": str(getattr(frame_meta, "source_id", "")),
                "frame_num": int(getattr(frame_meta, "frame_num", -1)),
                "object.count": len(objects_list),
            },
        ):
            frame = self._extract_frame(buffer, frame_meta) if self.write_crops else None
            gpu_ref = self._build_gpu_memory_ref(buffer, frame_meta, frame)

            if self.include_gpu_memory_ref:
                for obj in objects_list:
                    obj.attributes["gpu_memory_ref"] = dict(gpu_ref)

            if frame is None:
                for index, obj in enumerate(objects_list[: self.max_crops_per_frame]):
                    crop_path = self._crop_path(frame_meta, obj, index)
                    obj.attributes["crop_uri"] = self._public_uri(crop_path)
                    obj.attributes["crop_status"] = "pending_export" if not self.write_crops else "frame_unavailable"
                return

            self.output_dir.mkdir(parents=True, exist_ok=True)
            for index, obj in enumerate(objects_list[: self.max_crops_per_frame]):
                crop = self._crop_frame(frame, obj.bbox)
                if crop is None:
                    obj.attributes["crop_status"] = "bbox_out_of_frame"
                    continue
                crop_path = self._crop_path(frame_meta, obj, index)
                crop_path.parent.mkdir(parents=True, exist_ok=True)
                if self._write_jpeg(crop_path, crop):
                    obj.attributes["crop_uri"] = self._public_uri(crop_path)
                    obj.attributes["crop_status"] = "ok"
                else:
                    obj.attributes["crop_status"] = "write_failed"

    def _extract_frame(self, buffer: Any, frame_meta: Any) -> Optional[np.ndarray]:
        if isinstance(buffer, np.ndarray):
            return buffer

        try:
            import pyds

            batch_id = int(getattr(frame_meta, "batch_id", 0))
            try:
                surface = pyds.get_nvds_buf_surface(hash(buffer), batch_id)
                if surface is not None:
                    return np.array(surface, copy=True)
            except Exception:
                pass

            try:
                raw = pyds.get_buffer(buffer)
                if raw is not None:
                    width = int(getattr(frame_meta, "width", 0))
                    height = int(getattr(frame_meta, "height", 0))
                    return self._raw_buffer_to_array(raw, width, height)
            except Exception:
                pass
        except Exception:
            return None
        return None

    @staticmethod
    def _raw_buffer_to_array(raw: Any, width: int, height: int) -> Optional[np.ndarray]:
        if width <= 0 or height <= 0:
            return None
        expected_rgb = width * height * 3
        expected_rgba = width * height * 4
        raw_len = len(raw)
        if raw_len >= expected_rgba:
            return np.ndarray(shape=(height, width, 4), dtype=np.uint8, buffer=raw)
        if raw_len >= expected_rgb:
            return np.ndarray(shape=(height, width, 3), dtype=np.uint8, buffer=raw)
        return None

    @staticmethod
    def _crop_frame(frame: np.ndarray, bbox: Dict[str, float]) -> Optional[np.ndarray]:
        height, width = frame.shape[:2]
        left = max(0, int(float(bbox["left"])))
        top = max(0, int(float(bbox["top"])))
        right = min(width, int(float(bbox["left"]) + float(bbox["width"])))
        bottom = min(height, int(float(bbox["top"]) + float(bbox["height"])))
        if right <= left or bottom <= top:
            return None
        return frame[top:bottom, left:right].copy()

    def _crop_path(self, frame_meta: Any, obj: EventObject, index: int) -> Path:
        camera_id = self._safe_path_part(obj.camera_id)
        object_id = self._safe_path_part(str(obj.object_id))
        frame_num = int(getattr(frame_meta, "frame_num", 0))
        digest = hashlib.sha1(f"{obj.camera_id}:{obj.object_id}:{frame_num}:{index}".encode()).hexdigest()[:8]
        return self.output_dir / camera_id / object_id / f"frame_{frame_num:08d}_{digest}.jpg"

    def _public_uri(self, crop_path: Path) -> str:
        try:
            rel = crop_path.relative_to(self.output_dir).as_posix()
        except ValueError:
            rel = crop_path.name
        return f"{self.uri_prefix}/{rel}"

    def _write_jpeg(self, path: Path, crop: np.ndarray) -> bool:
        try:
            import cv2

            if crop.ndim == 3 and crop.shape[2] == 4:
                crop = cv2.cvtColor(crop, cv2.COLOR_RGBA2BGR)
            elif crop.ndim == 3 and crop.shape[2] == 3:
                crop = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
            return bool(cv2.imwrite(str(path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]))
        except Exception:
            return False

    @staticmethod
    def _build_gpu_memory_ref(buffer: Any, frame_meta: Any, frame: Optional[np.ndarray]) -> Dict[str, Any]:
        device_ptr = None
        if hasattr(frame, "__cuda_array_interface__"):
            try:
                device_ptr = int(frame.__cuda_array_interface__["data"][0])
            except Exception:
                device_ptr = None

        gst_buffer_ref = None
        try:
            gst_buffer_ref = hex(hash(buffer))
        except Exception:
            gst_buffer_ref = None

        host_array_ref = None
        if frame is not None:
            try:
                host_array_ref = hex(int(frame.__array_interface__["data"][0]))
            except Exception:
                host_array_ref = None

        return {
            "kind": "nvds_buffer_surface",
            "device_ptr": hex(device_ptr) if device_ptr else None,
            "device_ptr_available": device_ptr is not None,
            "gst_buffer_ref": gst_buffer_ref,
            "host_array_ref": host_array_ref,
            "batch_id": int(getattr(frame_meta, "batch_id", 0)),
            "frame_num": int(getattr(frame_meta, "frame_num", -1)),
            "note": "device_ptr is null when the Savant/PyDS Python binding exposes only a mapped host surface.",
        }

    @staticmethod
    def _safe_path_part(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:80]
