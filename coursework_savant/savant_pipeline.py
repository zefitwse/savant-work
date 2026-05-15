from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from coursework_savant.adaptive_inference import report_suspicious_targets
from coursework_savant.crop_exporter import TargetCropExporter
from coursework_savant.event_builder import (
    EventObject,
    SparseEventBuilder,
    fold_secondary_attributes,
)
from coursework_savant.model_switcher import ModelSwitchWatcher
from coursework_savant.telemetry import init_telemetry, start_span

try:
    from confluent_kafka import Producer
except ImportError:  # local unit tests can run without Kafka client installed
    Producer = None

try:
    from savant.deepstream.meta.frame import NvDsFrameMeta
    from savant.deepstream.pyfunc import NvDsPyFuncPlugin
    from savant.gstreamer import Gst
except ImportError:  # local interface tests run outside the Savant container
    class NvDsPyFuncPlugin:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.logger = _FallbackLogger()

    class Gst:  # type: ignore[no-redef]
        class Buffer:
            pass

    NvDsFrameMeta = Any  # type: ignore[assignment,misc]


PRIMARY_LABELS = {
    "person",
    "vehicle",
    "foreign_object",
    "car",
    "bicycle",
    "motorcycle",
    "bus",
    "truck",
    "road_sign",
}
SECONDARY_LABELS = {"hardhat", "no-hardhat", "vest", "no-vest"}
NORMALIZED_PRIMARY_LABELS = {
    "person": ("person", 0),
    "vehicle": ("vehicle", 1),
    "foreign_object": ("foreign_object", 2),
    "car": ("vehicle", 1),
    "bicycle": ("vehicle", 1),
    "motorcycle": ("vehicle", 1),
    "bus": ("vehicle", 1),
    "truck": ("vehicle", 1),
    "road_sign": ("foreign_object", 2),
}


class _FallbackLogger:
    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class EdgeEventProcessor(NvDsPyFuncPlugin):
    """Savant PyFunc that produces sparse Kafka events and cleans OSD metadata."""

    def __init__(
        self,
        kafka_bootstrap_servers: str = "kafka:19092",
        kafka_topic: str = "deepstream.events",
        ttl_frames: int = 90,
        attribute_cooldown_frames: int = 30,
        enable_kafka: bool = True,
        enable_crop_export: bool = True,
        crop_output_dir: str = "/workspace/deepstream_coursework/runtime/crops",
        crop_uri_prefix: str = "runtime/crops",
        include_gpu_memory_ref: bool = True,
        write_crops_in_pyfunc: bool = False,
        max_crops_per_frame: int = 16,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        init_telemetry("coursework-savant-edge")
        self.kafka_topic = kafka_topic
        self.event_builder = SparseEventBuilder(
            ttl_frames=ttl_frames,
            attribute_cooldown_frames=attribute_cooldown_frames,
        )
        self.crop_exporter = TargetCropExporter(
            output_dir=crop_output_dir,
            uri_prefix=crop_uri_prefix,
            enabled=enable_crop_export,
            include_gpu_memory_ref=include_gpu_memory_ref,
            write_crops=write_crops_in_pyfunc,
            max_crops_per_frame=max_crops_per_frame,
        )
        self.producer = None
        if enable_kafka and Producer is not None:
            self.producer = Producer({"bootstrap.servers": kafka_bootstrap_servers})

    def process_frame(self, buffer: Gst.Buffer, frame_meta: NvDsFrameMeta) -> None:
        with start_span(
            "savant.event.process_frame",
            {
                "camera_id": str(getattr(frame_meta, "source_id", "")),
                "frame_num": int(getattr(frame_meta, "frame_num", -1)),
            },
        ):
            primary_meta = []
            secondary_meta = []

            for obj_meta in list(frame_meta.objects):
                if getattr(obj_meta, "is_primary", False):
                    continue
                label = str(getattr(obj_meta, "label", ""))
                element_name = str(getattr(obj_meta, "element_name", ""))
                if label in SECONDARY_LABELS:
                    secondary_meta.append(obj_meta)
                    continue
                if label in PRIMARY_LABELS:
                    primary_meta.append(obj_meta)

            primary_events = [self._to_event_object(frame_meta, obj_meta) for obj_meta in primary_meta]
            secondary_events = [self._to_event_object(frame_meta, obj_meta) for obj_meta in secondary_meta]
            if primary_events:
                report_suspicious_targets(
                    str(getattr(frame_meta, "source_id", "")),
                    int(getattr(frame_meta, "frame_num", -1)),
                    len(primary_events),
                )
            fold_secondary_attributes(primary_events, secondary_events)
            self.crop_exporter.enrich(buffer, frame_meta, primary_events)

            for obj_meta, event_obj in zip(primary_meta, primary_events):
                self._update_draw_label(obj_meta, event_obj.attributes)

            for obj_meta in secondary_meta:
                frame_meta.remove_obj_meta(obj_meta)

            with start_span(
                "savant.event.build",
                {
                    "camera_id": str(getattr(frame_meta, "source_id", "")),
                    "frame_num": int(getattr(frame_meta, "frame_num", -1)),
                    "object.count": len(primary_events),
                },
            ):
                events = self.event_builder.update(int(frame_meta.frame_num), primary_events)
            for event in events:
                self._send_event(event)

            if self.producer is not None:
                self.producer.poll(0)

    def on_stop(self) -> None:
        if self.producer is not None:
            self.producer.flush(5)

    @staticmethod
    def _to_event_object(frame_meta: NvDsFrameMeta, obj_meta: Any) -> EventObject:
        bbox = obj_meta.bbox
        left = float(getattr(bbox, "left", 0.0))
        top = float(getattr(bbox, "top", 0.0))
        if left == 0.0 and top == 0.0 and hasattr(bbox, "xc"):
            left = float(bbox.xc - bbox.width / 2.0)
            top = float(bbox.yc - bbox.height / 2.0)
        raw_label = str(obj_meta.label)
        class_name, normalized_class_id = NORMALIZED_PRIMARY_LABELS.get(
            raw_label,
            (raw_label, int(getattr(obj_meta, "class_id", -1))),
        )
        return EventObject(
            camera_id=str(frame_meta.source_id),
            object_id=int(getattr(obj_meta, "track_id", getattr(obj_meta, "uid", -1))),
            class_id=normalized_class_id,
            class_name=class_name,
            confidence=float(getattr(obj_meta, "confidence", 0.0)),
            bbox={
                "left": left,
                "top": top,
                "width": float(bbox.width),
                "height": float(bbox.height),
            },
        )

    @staticmethod
    def _update_draw_label(obj_meta: Any, attributes: Dict[str, Any]) -> None:
        label_parts = [str(obj_meta.label)]
        for key in ["helmet", "workwear", "license_plate"]:
            if key in attributes:
                label_parts.append(f"{key}:{attributes[key]}")
        obj_meta.draw_label = " ".join(label_parts)

    def _send_event(self, event: Dict[str, Any]) -> None:
        with start_span(
            "savant.kafka.publish",
            {
                "camera_id": event.get("camera_id"),
                "track_id": event.get("track_id"),
                "event_type": event.get("event_type"),
                "kafka.topic": self.kafka_topic,
            },
        ):
            payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
            if self.producer is None:
                print(payload.decode("utf-8"))
                return
            key = f"{event['camera_id']}:{event['object_id']}".encode("utf-8")
            self.producer.produce(self.kafka_topic, key=key, value=payload)


class RuntimeControlProcessor(NvDsPyFuncPlugin):
    """Watches hot-swap state and marks frames with active model metadata.

    The API writes runtime/model_state.json. Savant can poll this command without
    restarting the container. Applying a new engine to a running nvinfer instance
    is runtime-version specific, so this class exposes the command to the module
    and leaves the low-level reload hook isolated in one place.
    """

    def __init__(
        self,
        model_state_path: str = "/workspace/deepstream_coursework/runtime/model_state.json",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        init_telemetry("coursework-savant-edge")
        self.watcher = ModelSwitchWatcher(Path(model_state_path))
        self.active_model: Optional[Dict[str, Any]] = None

    def process_frame(self, buffer: Gst.Buffer, frame_meta: NvDsFrameMeta) -> None:
        command = self.watcher.poll()
        if command is not None:
            with start_span(
                "savant.runtime_control.hotswap_command",
                {
                    "camera_id": str(getattr(frame_meta, "source_id", "")),
                    "frame_num": int(getattr(frame_meta, "frame_num", -1)),
                    "model.detector": command.detector,
                    "model.engine_path": command.engine_path,
                },
            ):
                self.active_model = {
                    "id": command.id,
                    "detector": command.detector,
                    "engine_path": command.engine_path,
                    "labels_path": command.labels_path,
                    "created_at": command.created_at,
                }
                self.logger.info("Received model hot-swap command: %s", self.active_model)

        if self.active_model is not None:
            frame_meta.set_tag("active_model", json.dumps(self.active_model))
