from __future__ import annotations

import time
from collections import deque
from enum import Enum
from typing import Any, Deque, Optional

import numpy as np

try:
    from savant.deepstream.meta.frame import NvDsFrameMeta
    from savant.deepstream.pyfunc import NvDsPyFuncPlugin
    from savant.gstreamer import Gst
except ImportError:
    class NvDsPyFuncPlugin:
        def __init__(self, **kwargs: Any) -> None:
            self.logger = _FallbackLogger()

    class Gst:
        class Buffer:
            pass

    NvDsFrameMeta = Any


class InferenceMode(Enum):
    IDLE = "idle"
    ALERT = "alert"


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
        motion_threshold: float = 50000.0,
        alert_threshold: float = 100000.0,
        idle_frame_interval: int = 5,
        alert_cooldown_frames: int = 30,
        history_size: int = 10,
        resize_width: int = 64,
        resize_height: int = 64,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.motion_threshold = motion_threshold
        self.alert_threshold = alert_threshold
        self.idle_frame_interval = idle_frame_interval
        self.alert_cooldown_frames = alert_cooldown_frames
        self.resize_width = resize_width
        self.resize_height = resize_height

        self._frame_history: Deque[np.ndarray] = deque(maxlen=2)
        self._motion_history: Deque[float] = deque(maxlen=history_size)
        self._idle_frame_counter = 0
        self._alert_cooldown_counter = 0
        self._current_mode = InferenceMode.IDLE
        self._frame_count = 0
        self._last_mode_switch_time = time.time()
        self._total_frames_processed = 0
        self._total_frames_dropped = 0

    def process_frame(self, buffer: Gst.Buffer, frame_meta: NvDsFrameMeta) -> None:
        self._frame_count += 1
        current_motion = self._compute_motion(buffer, frame_meta)

        self._motion_history.append(current_motion)
        avg_motion = sum(self._motion_history) / len(self._motion_history)

        prev_mode = self._current_mode
        self._update_mode(avg_motion)

        should_process = True
        if self._current_mode == InferenceMode.IDLE:
            self._idle_frame_counter += 1
            if self._idle_frame_counter >= self.idle_frame_interval:
                self._idle_frame_counter = 0
                should_process = True
            else:
                should_process = False
        else:
            self._idle_frame_counter = 0
            should_process = True

        if should_process:
            self._total_frames_processed += 1
        else:
            self._total_frames_dropped += 1

        frame_meta.set_tag("adaptive_inference.mode", self._current_mode.value)
        frame_meta.set_tag("adaptive_inference.should_process", str(should_process))
        frame_meta.set_tag("adaptive_inference.motion_score", str(int(avg_motion)))
        frame_meta.set_tag(
            "adaptive_inference.stats",
            f"processed:{self._total_frames_processed},dropped:{self._total_frames_dropped}"
        )

        if prev_mode != self._current_mode:
            self._last_mode_switch_time = time.time()
            self.logger.info(
                "Adaptive Inference: Mode switched from %s to %s. Motion: %.1f, "
                "Frames processed: %d, dropped: %d",
                prev_mode.value,
                self._current_mode.value,
                avg_motion,
                self._total_frames_processed,
                self._total_frames_dropped,
            )

    def _compute_motion(self, buffer: Gst.Buffer, frame_meta: NvDsFrameMeta) -> float:
        try:
            import cv2
            import pyds
        except ImportError:
            return 0.0

        try:
            frame_data = pyds.get_buffer(buffer)
            if frame_data is None or len(frame_data) == 0:
                return 0.0
        except Exception:
            return 0.0

        frame_width = int(frame_meta.width)
        frame_height = int(frame_meta.height)

        if frame_width <= 0 or frame_height <= 0:
            return 0.0

        n_frame = np.ndarray(
            shape=(frame_height, frame_width, 3),
            dtype=np.uint8,
            buffer=frame_data
        )

        gray = cv2.cvtColor(n_frame, cv2.COLOR_RGB2GRAY)
        resized = cv2.resize(gray, (self.resize_width, self.resize_height))

        if len(self._frame_history) == 2:
            self._frame_history.popleft()

        self._frame_history.append(resized)

        if len(self._frame_history) < 2:
            return 0.0

        prev_frame = self._frame_history[0]
        curr_frame = self._frame_history[1]

        diff = cv2.absdiff(prev_frame, curr_frame)
        motion_score = float(np.sum(diff))

        return motion_score

    def _update_mode(self, avg_motion: float) -> None:
        if self._current_mode == InferenceMode.IDLE:
            if avg_motion >= self.alert_threshold:
                self._current_mode = InferenceMode.ALERT
                self._alert_cooldown_counter = 0
        else:
            if avg_motion < self.motion_threshold:
                self._alert_cooldown_counter += 1
                if self._alert_cooldown_counter >= self.alert_cooldown_frames:
                    self._current_mode = InferenceMode.IDLE
                    self._alert_cooldown_counter = 0
            else:
                self._alert_cooldown_counter = 0

    def on_stop(self) -> None:
        self.logger.info(
            "Adaptive Inference Summary: Total frames: %d, Processed: %d, Dropped: %d, "
            "Final mode: %s",
            self._frame_count,
            self._total_frames_processed,
            self._total_frames_dropped,
            self._current_mode.value,
        )
