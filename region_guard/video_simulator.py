import time
import cv2

from region_guard.worker import RegionLogicWorker

VIDEO_PATH = r"D:\App\savant-work\savant-work-main\test.mp4"

A_ZONE = [[100, 100], [300, 100], [300, 500], [100, 500]]
B_ZONE = [[350, 100], [600, 100], [600, 500], [350, 500]]


def make_event(frame_id: int, track_id: str, x: int, y: int):
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
        "frame_id": frame_id,
    }


def draw_zone(frame, points, label, color):
    pts = [(int(x), int(y)) for x, y in points]
    for i in range(len(pts)):
        cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], color, 2)

    cv2.putText(
        frame,
        label,
        pts[0],
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        2,
    )


def main():
    worker = RegionLogicWorker()

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print(f"无法打开视频：{VIDEO_PATH}")
        return

    frame_id = 0
    latest_alert_text = ""

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_id += 1

        # 模拟同一个人：先进入 A 区，再进入 B 区，最后停在 B 区
        x = min(50 + frame_id * 3, 430)
        y = 250

        event = make_event(frame_id, "person_001", x, y)
        alerts = worker.process_event(event)

        for alert in alerts:
            latest_alert_text = f"{alert['alert_type']}: {alert['message']}"
            print("[TASK6 告警]", latest_alert_text)

        draw_zone(frame, A_ZONE, "A_warning", (0, 255, 255))
        draw_zone(frame, B_ZONE, "B_forbidden", (0, 0, 255))

        cv2.rectangle(frame, (x, y), (x + 80, y + 160), (0, 255, 0), 2)
        cv2.putText(
            frame,
            "person_001",
            (x, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )

        if latest_alert_text:
            cv2.rectangle(frame, (20, 20), (900, 80), (0, 0, 0), -1)
            cv2.putText(
                frame,
                latest_alert_text[:80],
                (30, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )

        cv2.imshow("task6 A-B tripwire demo", frame)

        if cv2.waitKey(30) & 0xFF == ord("q"):
            break

        time.sleep(0.03)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()