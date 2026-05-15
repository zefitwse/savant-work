import json
import time

import cv2

from stream_doctor.config import (
    BASELINE_FRAME_INTERVAL,
    BLUR_THRESHOLD,
    DARK_THRESHOLD,
    DB_PATH,
    OCCLUSION_EDGE_THRESHOLD,
    RECONNECT_INTERVAL_SECONDS,
    RECONNECT_MAX_ATTEMPTS,
    SHIFT_DIFF_THRESHOLD,
    SIGNAL_LOSS_LIMIT,
    VIDEO_SOURCE,
)
from stream_doctor.kafka_writer import VQDKafkaWriter
from stream_doctor.metrics import diagnose_frame
from stream_doctor.store import VQDStore


class VQDWorker:
    def __init__(self, video_source=VIDEO_SOURCE, camera_id="cam01"):
        self.video_source = video_source
        self.camera_id = camera_id
        self.store = VQDStore(DB_PATH)
        self.kafka_writer = VQDKafkaWriter()

        self.signal_loss_count = 0
        self.reconnect_attempts = 0
        self.baseline_frame = None

    def build_message(self, result):
        if result["status"] == "OK":
            return "视频质量正常"

        issue_text = {
            "DARK": "画面过暗",
            "BLUR": "画面模糊",
            "OCCLUSION": "疑似遮挡",
            "SHIFT": "摄像头疑似发生移位",
            "SIGNAL_LOSS": "信号丢失",
            "RECONNECTED": "视频流已自动重连",
        }

        return "；".join(issue_text.get(i, i) for i in result["issues"])

    def save_event(self, status, issues, metrics, message):
        event = self.store.save_event(
            camera_id=self.camera_id,
            status=status,
            issues=issues,
            metrics=metrics,
            message=message,
        )

        event["msg_version"] = "1.0"
        event["stream_id"] = self.camera_id
        event["stream_source"] = self.video_source
        event["event_type"] = "vqd_status"

        self.kafka_writer.send(event)

        print("[StreamDoctor VQD]", json.dumps(event, ensure_ascii=False, indent=2))
        return event

    def process_frame(self, frame):
        result = diagnose_frame(
            frame,
            dark_threshold=DARK_THRESHOLD,
            blur_threshold=BLUR_THRESHOLD,
            edge_threshold=OCCLUSION_EDGE_THRESHOLD,
            baseline_frame=self.baseline_frame,
            shift_threshold=SHIFT_DIFF_THRESHOLD,
        )

        message = self.build_message(result)

        return self.save_event(
            status=result["status"],
            issues=result["issues"],
            metrics=result["metrics"],
            message=message,
        )

    def save_signal_loss(self):
        return self.save_event(
            status="MAINTENANCE",
            issues=["SIGNAL_LOSS"],
            metrics={
                "signal_loss_count": self.signal_loss_count,
                "reconnect_attempts": self.reconnect_attempts,
            },
            message="RTSP/视频流读取失败，进入维护中状态，正在尝试自动重连",
        )

    def save_reconnected(self):
        return self.save_event(
            status="OK",
            issues=["RECONNECTED"],
            metrics={
                "reconnect_attempts": self.reconnect_attempts,
            },
            message="视频流自动重连成功，恢复正常",
        )

    def open_capture(self):
        return cv2.VideoCapture(self.video_source)

    def try_reconnect(self):
        while self.reconnect_attempts < RECONNECT_MAX_ATTEMPTS:
            self.reconnect_attempts += 1
            print(
                f"[StreamDoctor] 正在尝试自动重连 {self.reconnect_attempts}/{RECONNECT_MAX_ATTEMPTS} ..."
            )

            time.sleep(RECONNECT_INTERVAL_SECONDS)

            cap = self.open_capture()

            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    self.signal_loss_count = 0
                    self.save_reconnected()
                    return cap, frame

            cap.release()

        print("[StreamDoctor] 自动重连失败，保持维护中状态")
        return None, None

    def run(self, show=True):
        cap = self.open_capture()

        if not cap.isOpened():
            self.signal_loss_count = SIGNAL_LOSS_LIMIT
            self.save_signal_loss()

            cap, first_frame = self.try_reconnect()
            if cap is None:
                return
        else:
            first_frame = None

        frame_id = 0

        while True:
            if first_frame is not None:
                ret = True
                frame = first_frame
                first_frame = None
            else:
                ret, frame = cap.read()

            if not ret:
                self.signal_loss_count += 1

                if self.signal_loss_count >= SIGNAL_LOSS_LIMIT:
                    self.save_signal_loss()

                    cap.release()
                    cap, first_frame = self.try_reconnect()

                    if cap is None:
                        break

                    continue

                continue

            self.signal_loss_count = 0
            frame_id += 1

            if self.baseline_frame is None and frame_id >= BASELINE_FRAME_INTERVAL:
                self.baseline_frame = frame.copy()
                print("[StreamDoctor] 已设置基准画面，用于摄像头移位检测")

            if frame_id % 30 == 0:
                self.process_frame(frame)

            if show:
                display = frame.copy()

                if self.baseline_frame is not None:
                    result = diagnose_frame(
                        frame,
                        dark_threshold=DARK_THRESHOLD,
                        blur_threshold=BLUR_THRESHOLD,
                        edge_threshold=OCCLUSION_EDGE_THRESHOLD,
                        baseline_frame=self.baseline_frame,
                        shift_threshold=SHIFT_DIFF_THRESHOLD,
                    )
                    cv2.putText(
                        display,
                        f"Status: {result['status']} Issues: {result['issues']}",
                        (30, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 255),
                        2,
                    )
                    cv2.putText(
                        display,
                        f"Shift score: {result['metrics']['shift_score']:.2f}",
                        (30, 80),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 255),
                        2,
                    )

                cv2.imshow("task9 video quality diagnosis", display)

                if cv2.waitKey(30) & 0xFF == ord("q"):
                    break

            time.sleep(0.01)

        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    VQDWorker().run(show=True)
