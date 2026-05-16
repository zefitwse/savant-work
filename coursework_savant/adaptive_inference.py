from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Mapping, Optional

import numpy as np

try:
    from savant.deepstream.meta.frame import NvDsFrameMeta
    from savant.deepstream.pyfunc import NvDsPyFuncPlugin
    from savant.gstreamer import Gst
except ImportError:
    class NvDsPyFuncPlugin:
        def __init__(self, **kwargs: Any) -> None:
            self.logger = _FallbackLogger()
            self.gst_element = None

        def on_start(self) -> bool:
            return True

    class Gst:
        class Buffer:
            pass

    NvDsFrameMeta = Any


class InferenceMode(Enum):
    PAUSED = "paused"
    IDLE = "idle"
    ALERT = "alert"


@dataclass(frozen=True)
class InferencePolicy:
    idle_fps: float = 5.0
    active_fps: float = 25.0
    motion_mask_enabled: bool = True
    motion_threshold: float = 50000.0
    alert_threshold: float = 100000.0
    static_cooldown_frames: int = 50
    target_cooldown_frames: int = 125
    paused_interval: int = 250
    paused_probe_interval_frames: int = 25
    segment_warmup_frames: int = 10
    config_poll_interval_sec: float = 1.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InferencePolicy":
        defaults = cls()
        return cls(
            idle_fps=float(value.get("idle_fps", defaults.idle_fps)),
            active_fps=float(value.get("active_fps", defaults.active_fps)),
            motion_mask_enabled=bool(value.get("motion_mask_enabled", defaults.motion_mask_enabled)),
            motion_threshold=float(value.get("motion_threshold", defaults.motion_threshold)),
            alert_threshold=float(value.get("alert_threshold", defaults.alert_threshold)),
            static_cooldown_frames=int(value.get("static_cooldown_frames", defaults.static_cooldown_frames)),
            target_cooldown_frames=int(value.get("target_cooldown_frames", defaults.target_cooldown_frames)),
            paused_interval=min(250, int(value.get("paused_interval", defaults.paused_interval))),
            paused_probe_interval_frames=max(
                1,
                int(value.get("paused_probe_interval_frames", defaults.paused_probe_interval_frames)),
            ),
            segment_warmup_frames=max(
                0,
                int(value.get("segment_warmup_frames", defaults.segment_warmup_frames)),
            ),
            config_poll_interval_sec=float(
                value.get("config_poll_interval_sec", defaults.config_poll_interval_sec)
            ),
        )

    def infer_interval(self, mode: InferenceMode, input_fps: float) -> int:
        if mode == InferenceMode.PAUSED:
            return max(1, self.paused_interval)
        target_fps = self.active_fps if mode == InferenceMode.ALERT else self.idle_fps
        return fps_to_nvinfer_interval(input_fps=input_fps, target_fps=target_fps)


@dataclass
class _SourceRuntimeState:
    frame_history: Deque[np.ndarray] = field(default_factory=lambda: deque(maxlen=2))
    motion_history: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    mode: InferenceMode = InferenceMode.IDLE
    static_frames: int = 0
    processed_frames: int = 0
    dropped_frames: int = 0
    cadence_counter: int = 0
    last_target_frame: Optional[int] = None
    last_target_count: int = 0
    alert_hold_until: float = 0.0
    last_seen_frame_num: Optional[int] = None
    warmup_until_frame: Optional[int] = None

    def reset_segment(self, frame_num: int, warmup_frames: int) -> None:
        self.frame_history.clear()
        self.motion_history.clear()
        self.mode = InferenceMode.IDLE
        self.static_frames = 0
        self.cadence_counter = 0
        self.last_target_frame = None
        self.last_target_count = 0
        self.alert_hold_until = 0.0
        self.warmup_until_frame = frame_num + max(0, warmup_frames)


class _SharedInferenceRuntime:
    def __init__(self) -> None:
        self.sources: Dict[str, _SourceRuntimeState] = {}

    def state(self, source_id: str, history_size: int) -> _SourceRuntimeState:
        state = self.sources.get(source_id)
        if state is None:
            state = _SourceRuntimeState()
            state.motion_history = deque(maxlen=history_size)
            self.sources[source_id] = state
        return state

    def report_targets(self, source_id: str, frame_num: int, object_count: int) -> None:
        if object_count <= 0:
            return
        state = self.state(source_id, history_size=10)
        state.last_target_frame = frame_num
        state.last_target_count = object_count


SHARED_RUNTIME = _SharedInferenceRuntime()
ALERT_STATE_DIR = Path(
    os.getenv(
        "ADAPTIVE_ALERT_STATE_DIR",
        "/workspace/deepstream_coursework/runtime/adaptive_alert_state",
    )
)
ALERT_STATE_LEGACY_PATH = Path("/workspace/deepstream_coursework/runtime/adaptive_alert_state.json")


def _safe_source_file(source_id: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(source_id).strip())
    return name or "default"


def _write_alert_state_atomic(
    state_dir: Path,
    source_id: str,
    frame_num: int,
    object_count: int,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{_safe_source_file(source_id)}.json"
    tmp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    payload = {
        "source_id": str(source_id),
        "last_target_frame": int(frame_num),
        "object_count": int(object_count),
        "updated_at": time.time(),
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(state_path)


def report_suspicious_targets(source_id: str, frame_num: int, object_count: int) -> None:
    """Called after detection/tracking to raise following frames to full FPS."""
    SHARED_RUNTIME.report_targets(source_id, frame_num, object_count)
    try:
        _write_alert_state_atomic(ALERT_STATE_DIR, source_id, frame_num, object_count)
    except Exception:
        pass


def fps_to_nvinfer_interval(input_fps: float, target_fps: float) -> int:
    if input_fps <= 0 or target_fps <= 0:
        return 0
    if target_fps >= input_fps:
        return 0
    return max(0, int(round(input_fps / target_fps)) - 1)


class _FallbackLogger:
    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class AdaptiveInferenceController(NvDsPyFuncPlugin):
    def __init__(
        self,
        policy_path: str = "/workspace/deepstream_coursework/runtime/inference_policy.json",
        config_output_dir: str = "/workspace/deepstream_coursework/runtime/nvinfer_configs",
        nvinfer_elements: Optional[Iterable[Mapping[str, str]]] = None,
        motion_threshold: float = 50000.0,
        alert_threshold: float = 100000.0,
        idle_frame_interval: int = 5,
        alert_cooldown_frames: int = 125,
        history_size: int = 10,
        resize_width: int = 64,
        resize_height: int = 64,
        alert_state_dir: str = str(ALERT_STATE_DIR),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.policy_path = Path(policy_path)
        self.config_output_dir = Path(config_output_dir)
        self.alert_state_dir = Path(alert_state_dir)
        self.history_size = history_size
        self.resize_width = resize_width
        self.resize_height = resize_height
        self._fallback_policy = InferencePolicy(
            idle_fps=25.0 / max(1, idle_frame_interval),
            active_fps=25.0,
            motion_threshold=motion_threshold,
            alert_threshold=alert_threshold,
            target_cooldown_frames=alert_cooldown_frames,
        )
        self._policy = self._fallback_policy
        self._camera_policies: Dict[str, InferencePolicy] = {}
        self._last_policy_load = 0.0
        self._last_policy_mtime: Optional[float] = None
        self._last_alert_mtime: Optional[float] = None
        self._external_alerts: Dict[str, Dict[str, Any]] = {}
        self._nvinfer_specs = [
            {
                "name": "primary_traffic_detector",
                "base_config": "/workspace/deepstream_coursework/models/primary_yolo_coco/yolov8n_coco_config_savant.txt",
            },
            {
                "name": "yolo_ppe_secondary",
                "base_config": "/workspace/deepstream_coursework/models/yolo/best_config_savant.txt",
            },
        ]
        if nvinfer_elements:
            self._nvinfer_specs = [dict(item) for item in nvinfer_elements]
        self._nvinfer_elements: Dict[str, Any] = {}
        self._buffer_decisions: Dict[int, bool] = {}
        self._gate_probe_installed = False
        self._active_interval: Optional[int] = None
        self._variant_paths: Dict[int, Dict[str, Path]] = {}
        self._frame_count = 0

    def on_start(self) -> bool:
        parent_started = super().on_start()
        self._load_policy(force=True)
        self._resolve_nvinfer_elements()
        return parent_started

    def process_frame(self, buffer: Gst.Buffer, frame_meta: NvDsFrameMeta) -> None:
        self._frame_count += 1
        self._load_policy()
        self._load_external_alerts()

        source_id = str(getattr(frame_meta, "source_id", "default"))
        frame_num = int(getattr(frame_meta, "frame_num", self._frame_count))
        input_fps = parse_framerate(getattr(frame_meta, "framerate", None)) or 25.0
        policy = self._camera_policies.get(source_id, self._policy)
        state = SHARED_RUNTIME.state(source_id, self.history_size)
        if state.last_seen_frame_num is not None and frame_num < state.last_seen_frame_num:
            state.reset_segment(frame_num, policy.segment_warmup_frames)

        motion_score = self._compute_motion(buffer, frame_meta, state)
        state.motion_history.append(motion_score)
        avg_motion = sum(state.motion_history) / len(state.motion_history)

        previous_mode = state.mode
        state.mode = self._select_mode(source_id, state, frame_num, avg_motion, policy, input_fps)
        interval = policy.infer_interval(state.mode, input_fps)
        state.cadence_counter += 1
        should_process = self._should_process_frame(state, interval, policy, frame_num)
        effective_interval = (
            0
            if state.mode == InferenceMode.PAUSED and should_process
            else interval
        )

        if should_process:
            state.processed_frames += 1
        else:
            state.dropped_frames += 1

        self._apply_interval(effective_interval)
        self._write_tags(frame_meta, state, avg_motion, interval, should_process, input_fps, effective_interval)
        state.last_seen_frame_num = frame_num

        if previous_mode != state.mode:
            self.logger.info(
                "Adaptive inference mode changed for source %s: %s -> %s, motion=%.1f, interval=%d",
                source_id,
                previous_mode.value,
                state.mode.value,
                avg_motion,
                interval,
            )

    @staticmethod
    def _should_process_frame(
        state: _SourceRuntimeState,
        interval: int,
        policy: InferencePolicy,
        frame_num: int,
    ) -> bool:
        if state.warmup_until_frame is not None:
            if frame_num <= state.warmup_until_frame:
                return True
            state.warmup_until_frame = None
        if state.mode == InferenceMode.PAUSED or interval >= policy.paused_interval:
            return (
                (state.cadence_counter - 1)
                % max(1, policy.paused_probe_interval_frames)
                == 0
            )
        if state.mode == InferenceMode.ALERT:
            return True
        return (state.cadence_counter - 1) % (interval + 1) == 0

    def _select_mode(
        self,
        source_id: str,
        state: _SourceRuntimeState,
        frame_num: int,
        avg_motion: float,
        policy: InferencePolicy,
        input_fps: float,
    ) -> InferenceMode:
        target_recent = (
            state.last_target_frame is not None
            and 0 <= frame_num - state.last_target_frame <= policy.target_cooldown_frames
        )
        external_alert = self._external_alerts.get(source_id)
        if external_alert:
            target_recent = target_recent or (
                time.time() - float(external_alert.get("updated_at", 0.0))
                <= policy.target_cooldown_frames / max(input_fps, 1.0)
            )
        if target_recent or avg_motion >= policy.alert_threshold:
            state.static_frames = 0
            state.alert_hold_until = time.time() + policy.target_cooldown_frames / max(input_fps, 1.0)
            return InferenceMode.ALERT

        if state.mode == InferenceMode.ALERT and time.time() < state.alert_hold_until:
            return InferenceMode.ALERT

        if not policy.motion_mask_enabled:
            state.static_frames = 0
            return InferenceMode.IDLE

        if avg_motion < policy.motion_threshold:
            state.static_frames += 1
            if state.static_frames >= policy.static_cooldown_frames:
                return InferenceMode.PAUSED
        else:
            state.static_frames = 0

        return InferenceMode.IDLE

    def _compute_motion(
        self,
        buffer: Gst.Buffer,
        frame_meta: NvDsFrameMeta,
        state: _SourceRuntimeState,
    ) -> float:
        frame = self._extract_frame(buffer, frame_meta)
        if frame is None:
            return 0.0

        try:
            import cv2

            if frame.ndim == 3 and frame.shape[2] == 4:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGBA2GRAY)
            elif frame.ndim == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            else:
                gray = frame
            resized = cv2.resize(gray, (self.resize_width, self.resize_height))
        except Exception:
            return 0.0

        state.frame_history.append(resized)
        if len(state.frame_history) < 2:
            return 0.0

        prev_frame = state.frame_history[0]
        curr_frame = state.frame_history[1]
        try:
            import cv2

            diff = cv2.absdiff(prev_frame, curr_frame)
            return float(np.sum(diff))
        except Exception:
            return 0.0

    @staticmethod
    def _extract_frame(buffer: Any, frame_meta: Any) -> Optional[np.ndarray]:
        if isinstance(buffer, np.ndarray):
            return buffer
        try:
            import pyds

            try:
                raw = pyds.get_buffer(buffer)
                if raw is not None:
                    width = int(getattr(frame_meta, "width", 0))
                    height = int(getattr(frame_meta, "height", 0))
                    channels = 4 if len(raw) >= width * height * 4 else 3
                    return np.ndarray(shape=(height, width, channels), dtype=np.uint8, buffer=raw)
            except Exception:
                pass
        except Exception:
            return None
        return None

    def _write_tags(
        self,
        frame_meta: NvDsFrameMeta,
        state: _SourceRuntimeState,
        avg_motion: float,
        interval: int,
        should_process: bool,
        input_fps: float,
        effective_interval: int,
    ) -> None:
        requested_fps = 0.0 if state.mode == InferenceMode.PAUSED else input_fps / (interval + 1)
        frame_meta.set_tag("adaptive_inference.mode", state.mode.value)
        frame_meta.set_tag("adaptive_inference.should_process", str(should_process))
        frame_meta.set_tag("adaptive_inference.motion_score", str(int(avg_motion)))
        frame_meta.set_tag("adaptive_inference.requested_fps", f"{requested_fps:.2f}")
        frame_meta.set_tag("adaptive_inference.nvinfer_interval", str(interval))
        frame_meta.set_tag("adaptive_inference.effective_nvinfer_interval", str(effective_interval))
        frame_meta.set_tag(
            "adaptive_inference.stats",
            f"processed:{state.processed_frames},dropped:{state.dropped_frames}",
        )

    def _load_policy(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_policy_load < self._policy.config_poll_interval_sec:
            return
        self._last_policy_load = now
        if not self.policy_path.exists():
            self._policy = self._fallback_policy
            self._camera_policies = {}
            return

        try:
            mtime = self.policy_path.stat().st_mtime
            if not force and self._last_policy_mtime == mtime:
                return
            payload = json.loads(self.policy_path.read_text(encoding="utf-8"))
            policy_payload = payload.get("default", payload)
            self._policy = InferencePolicy.from_mapping(policy_payload)
            self._camera_policies = {
                str(source_id): InferencePolicy.from_mapping(camera_payload)
                for source_id, camera_payload in payload.get("cameras", {}).items()
                if isinstance(camera_payload, Mapping)
            }
            self._last_policy_mtime = mtime
            self.logger.info("Loaded adaptive inference policy: %s", policy_payload)
        except Exception as exc:
            self.logger.warning("Failed to load adaptive inference policy %s: %s", self.policy_path, exc)
            self._policy = self._fallback_policy
            self._camera_policies = {}

    def _load_external_alerts(self) -> None:
        try:
            state_files = sorted(self.alert_state_dir.glob("*.json")) if self.alert_state_dir.exists() else []
            if not state_files and not ALERT_STATE_LEGACY_PATH.exists():
                self._external_alerts = {}
                return
            mtimes = []
            existing_state_files = []
            for path in state_files:
                try:
                    mtimes.append(path.stat().st_mtime)
                    existing_state_files.append(path)
                except FileNotFoundError:
                    continue
            state_files = existing_state_files
            if not state_files and ALERT_STATE_LEGACY_PATH.exists():
                mtimes.append(ALERT_STATE_LEGACY_PATH.stat().st_mtime)
            mtime = max(mtimes) if mtimes else 0.0
            if self._last_alert_mtime == mtime:
                return

            alerts: Dict[str, Dict[str, Any]] = {}
            for state_file in state_files:
                try:
                    payload = json.loads(state_file.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    self.logger.warning("Failed to load adaptive alert state %s: %s", state_file, exc)
                    continue
                if not isinstance(payload, Mapping):
                    continue
                source_id = str(payload.get("source_id") or state_file.stem)
                alerts[source_id] = dict(payload)

            if not alerts and ALERT_STATE_LEGACY_PATH.exists():
                try:
                    payload = json.loads(ALERT_STATE_LEGACY_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, Mapping):
                        alerts = {
                            str(key): dict(value)
                            for key, value in payload.items()
                            if isinstance(value, Mapping)
                        }
                except Exception as exc:
                    self.logger.warning("Ignoring invalid legacy adaptive alert state: %s", exc)

            self._external_alerts = alerts
            self._last_alert_mtime = mtime
        except Exception as exc:
            self.logger.warning("Failed to load adaptive alert state: %s", exc)

    def _resolve_nvinfer_elements(self) -> None:
        if self.gst_element is None:
            return
        pipeline = self.gst_element.get_parent()
        if pipeline is None:
            return
        for spec in self._nvinfer_specs:
            name = spec["name"]
            element = pipeline.get_by_name(name)
            if element is None:
                self.logger.warning("Unable to find nvinfer element %s for adaptive switching.", name)
                continue
            self._nvinfer_elements[name] = element

    def _apply_interval(self, interval: int) -> None:
        if self._active_interval == interval:
            return
        if not self._nvinfer_elements:
            self._resolve_nvinfer_elements()
        if not self._nvinfer_elements:
            self._active_interval = interval
            return

        changed = False
        for name, element in self._nvinfer_elements.items():
            try:
                element.set_property("interval", interval)
                changed = True
            except Exception as exc:
                self.logger.warning(
                    "Failed to switch nvinfer interval for %s to %d: %s",
                    name,
                    interval,
                    exc,
                )
        if changed:
            self.logger.info("Applied adaptive nvinfer interval=%d.", interval)
        self._active_interval = interval

    def _ensure_variant_configs(self, interval: int) -> Dict[str, Path]:
        paths = self._variant_paths.get(interval)
        if paths is not None:
            return paths

        self.config_output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for spec in self._nvinfer_specs:
            name = spec["name"]
            base_path = Path(spec["base_config"])
            if not base_path.exists():
                self.logger.warning("Base nvinfer config does not exist yet: %s", base_path)
                continue
            content = base_path.read_text(encoding="utf-8")
            variant = update_nvinfer_interval_config(content, interval, base_path.parent)
            variant_path = self.config_output_dir / f"{name}_interval_{interval}.txt"
            variant_path.write_text(variant, encoding="utf-8")
            paths[name] = variant_path

        self._variant_paths[interval] = paths
        return paths

    def on_stop(self) -> None:
        self.logger.info("Adaptive Inference Summary: Total frames: %d", self._frame_count)


def parse_framerate(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value)
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            return float(left) / denominator
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def update_nvinfer_interval_config(
    content: str,
    interval: int,
    base_dir: Optional[Path] = None,
) -> str:
    keys = {"secondary-reinfer-interval", "interval"}
    path_keys = {
        "onnx-file",
        "model-engine-file",
        "labelfile-path",
        "int8-calib-file",
        "custom-lib-path",
        "parse-bbox-func-name",
    }
    lines = content.splitlines()
    replaced = False
    output = []
    in_property = False
    insert_at: Optional[int] = None

    for line in lines:
        stripped = line.strip()
        if stripped == "[property]":
            in_property = True
        elif stripped.startswith("[") and stripped.endswith("]"):
            if in_property and insert_at is None:
                insert_at = len(output)
            in_property = False

        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if in_property and key in keys:
            output.append(f"{key} = {interval}")
            replaced = True
        elif in_property and key in path_keys and "=" in stripped and base_dir is not None:
            left, right = line.split("=", 1)
            value = right.strip()
            if key == "parse-bbox-func-name" or not value or Path(value).is_absolute() or "://" in value:
                output.append(line)
            else:
                output.append(f"{left.rstrip()} = {(base_dir / value).as_posix()}")
        else:
            output.append(line)

    if not replaced:
        if insert_at is None:
            insert_at = len(output)
        output.insert(insert_at, f"secondary-reinfer-interval = {interval}")

    return "\n".join(output) + ("\n" if content.endswith("\n") else "")
