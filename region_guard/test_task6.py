# task6/test_task6.py
import time

from region_guard.worker import RegionLogicWorker


def test_forbidden_zone():
    worker = RegionLogicWorker()

    event = {
        "camera_id": "cam01",
        "track_id": "t001",
        "class_name": "person",
        "event_type": "object_entered",
        "bbox": {
            "left": 400,
            "top": 200,
            "width": 80,
            "height": 160,
        },
        "timestamp": time.time(),
    }

    alerts = worker.process_event(event)

    assert len(alerts) >= 1
    assert alerts[0]["alert_type"] == "FORBIDDEN_ZONE"


if __name__ == "__main__":
    test_forbidden_zone()
    print("task6 test passed")
