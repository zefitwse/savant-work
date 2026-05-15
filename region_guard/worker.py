import json
import time
from collections import defaultdict

from region_guard.config import (
    DB_PATH,
    DENSITY_THRESHOLD,
    GROUP_ID,
    INPUT_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
    LOITERING_SECONDS,
    OUTPUT_TOPIC,
    TRIPWIRE_RULES,
)
from region_guard.geometry import bbox_to_foot_point, find_rois
from region_guard.roi_manager import ROIManager
from region_guard.store import AlertStore


class RegionLogicWorker:
    def __init__(self):
        self.store = AlertStore(DB_PATH)
        self.roi_manager = ROIManager()

        self.track_roi_enter_time = defaultdict(dict)
        self.roi_active_tracks = defaultdict(set)
        self.track_history = defaultdict(set)
        self.tripwire_triggered = defaultdict(set)
        self.loitering_triggered = defaultdict(set)

        self.producer = None
        self.consumer = None

    def build_alert(self, event: dict, alert_type: str, roi_names: list[str], message: str) -> dict:
        camera_id = str(event.get("camera_id", "unknown"))
        stream_id = str(event.get("stream_id", camera_id))
        track_id = str(event.get("track_id", event.get("object_id", "unknown")))
        class_name = str(event.get("class", event.get("class_name", "unknown")))
        bbox = event.get("bbox", {})

        if isinstance(bbox, dict):
            bbox_xywh = [
                float(bbox.get("left", 0.0)),
                float(bbox.get("top", 0.0)),
                float(bbox.get("width", 0.0)),
                float(bbox.get("height", 0.0)),
            ]
        else:
            bbox_xywh = bbox

        alert = self.store.save_alert(
            camera_id=camera_id,
            track_id=track_id,
            alert_type=alert_type,
            roi_names=roi_names,
            bbox=bbox,
            message=message,
        )
        alert["msg_version"] = "1.0"
        alert["stream_id"] = stream_id
        alert["track_id"] = track_id
        alert["class"] = class_name
        alert["bbox_xywh"] = bbox_xywh
        alert["event_type"] = "region_alert"
        return alert

    def clear_track(self, track_id: str):
        for roi_name in list(self.track_roi_enter_time[track_id].keys()):
            self.roi_active_tracks[roi_name].discard(track_id)

        self.track_roi_enter_time.pop(track_id, None)
        self.track_history.pop(track_id, None)
        self.tripwire_triggered.pop(track_id, None)
        self.loitering_triggered.pop(track_id, None)

    def check_tripwire(self, event: dict, track_id: str, current_roi_names: list[str]) -> list[dict]:
        alerts = []

        for rule in TRIPWIRE_RULES:
            rule_name = rule["name"]
            from_roi = rule["from"]
            to_roi = rule["to"]

            already_passed_from = from_roi in self.track_history[track_id]
            now_in_to = to_roi in current_roi_names
            not_triggered = rule_name not in self.tripwire_triggered[track_id]

            if already_passed_from and now_in_to and not_triggered:
                alerts.append(
                    self.build_alert(
                        event,
                        "TRIPWIRE_A_TO_B",
                        [from_roi, to_roi],
                        f"目标 {track_id} 已先经过 {from_roi}，随后进入 {to_roi}",
                    )
                )
                self.tripwire_triggered[track_id].add(rule_name)

        return alerts

    def process_event(self, event: dict) -> list[dict]:
        camera_id = str(event.get("camera_id", "cam01"))
        track_id = str(event.get("track_id", event.get("object_id", "unknown")))
        event_type = event.get("event_type", "object_update")

        alerts = []

        if event_type in ("object_expired", "expired", "leave"):
            self.clear_track(track_id)
            return alerts

        point = bbox_to_foot_point(event)
        roi_config = self.roi_manager.get_all()
        rois = find_rois(camera_id, point, roi_config)
        current_roi_names = [roi["name"] for roi in rois]

        now = time.time()

        for roi_name in current_roi_names:
            self.track_history[track_id].add(roi_name)

        alerts.extend(self.check_tripwire(event, track_id, current_roi_names))

        for roi in rois:
            roi_name = roi["name"]
            roi_type = roi.get("type", "warning")

            self.roi_active_tracks[roi_name].add(track_id)

            first_enter = roi_name not in self.track_roi_enter_time[track_id]

            if first_enter:
                self.track_roi_enter_time[track_id][roi_name] = now

                if roi_type == "forbidden":
                    alerts.append(
                        self.build_alert(
                            event,
                            "FORBIDDEN_ZONE",
                            [roi_name],
                            f"目标 {track_id} 进入禁区 {roi_name}",
                        )
                    )

            stay_time = now - self.track_roi_enter_time[track_id][roi_name]

            if stay_time >= LOITERING_SECONDS and roi_name not in self.loitering_triggered[track_id]:
                alerts.append(
                    self.build_alert(
                        event,
                        "LOITERING",
                        [roi_name],
                        f"目标 {track_id} 在 {roi_name} 停留超过 {LOITERING_SECONDS} 秒",
                    )
                )
                self.loitering_triggered[track_id].add(roi_name)

            density = len(self.roi_active_tracks[roi_name])
            if density >= DENSITY_THRESHOLD:
                alerts.append(
                    self.build_alert(
                        event,
                        "DENSITY",
                        [roi_name],
                        f"区域 {roi_name} 当前目标数 {density}，超过阈值 {DENSITY_THRESHOLD}",
                    )
                )

        return alerts

    def publish_alert(self, alert: dict):
        if not self.producer:
            print("[RegionGuard ALERT]", json.dumps(alert, ensure_ascii=False))
            return

        self.producer.send(
            OUTPUT_TOPIC,
            key=alert["camera_id"].encode("utf-8"),
            value=alert,
        )
        self.producer.flush()

    def run_with_kafka(self):
        from kafka import KafkaConsumer, KafkaProducer

        self.consumer = KafkaConsumer(
            INPUT_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=GROUP_ID,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )

        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        )

        print(f"[RegionGuard] Kafka consumer started: {INPUT_TOPIC}")
        print(f"[RegionGuard] Kafka producer output: {OUTPUT_TOPIC}")

        for msg in self.consumer:
            event = msg.value
            alerts = self.process_event(event)
            for alert in alerts:
                self.publish_alert(alert)


def demo():
    worker = RegionLogicWorker()

    events = [
        {
            "camera_id": "cam01",
            "track_id": "person_001",
            "class_name": "person",
            "event_type": "object_update",
            "bbox": {"left": 150, "top": 200, "width": 80, "height": 160},
            "timestamp": time.time(),
        },
        {
            "camera_id": "cam01",
            "track_id": "person_001",
            "class_name": "person",
            "event_type": "object_update",
            "bbox": {"left": 400, "top": 200, "width": 80, "height": 160},
            "timestamp": time.time(),
        },
    ]

    for event in events:
        alerts = worker.process_event(event)
        for alert in alerts:
            print(json.dumps(alert, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        demo()
    else:
        RegionLogicWorker().run_with_kafka()
