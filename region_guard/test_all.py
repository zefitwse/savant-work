import time

from region_guard.worker import RegionLogicWorker


def make_event(track_id, x, y=200):
    return {
        "camera_id": "cam01",
        "track_id": track_id,
        "class_name": "person",
        "event_type": "object_update",
        "bbox": {
            "left": x,
            "top": y,
            "width": 80,
            "height": 160,
        },
        "timestamp": time.time(),
    }


def main():
    worker = RegionLogicWorker()

    print("\n==== 1. 测试禁区进入 ====")
    alerts = worker.process_event(make_event("p1", 400))
    for a in alerts:
        print(a["alert_type"], a["message"])

    print("\n==== 2. 测试 A区 -> B区 Tripwire ====")
    worker = RegionLogicWorker()
    worker.process_event(make_event("p2", 150))
    alerts = worker.process_event(make_event("p2", 400))
    for a in alerts:
        print(a["alert_type"], a["message"])

    print("\n==== 3. 测试停留检测 Loitering ====")
    worker = RegionLogicWorker()
    worker.process_event(make_event("p3", 400))
    print("等待 6 秒...")
    time.sleep(6)
    alerts = worker.process_event(make_event("p3", 410))
    for a in alerts:
        print(a["alert_type"], a["message"])

    print("\n==== 4. 测试密度检测 Density ====")
    worker = RegionLogicWorker()
    worker.process_event(make_event("p4", 400))
    worker.process_event(make_event("p5", 410))
    alerts = worker.process_event(make_event("p6", 420))
    for a in alerts:
        print(a["alert_type"], a["message"])


if __name__ == "__main__":
    main()
