# task6/video_simulator.py
import time
import cv2

from region_guard.worker import RegionLogicWorker


VIDEO_PATH = "test.mp4"


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


def main():
    worker = RegionLogicWorker()

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print(f"无法打开视频：{VIDEO_PATH}")
        print("请把测试视频命名为 test.mp4，放到 WORK 目录下")
        return

    frame_id = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_id += 1

        # 模拟一个人从左往右走
        x = 50 + frame_id * 5
        y = 250

        event = make_event(frame_id, "person_001", x, y)
        alerts = worker.process_event(event)

        for alert in alerts:
            print("[TASK6 告警]", alert)

        # 画出模拟检测框
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

        cv2.imshow("task6 local video test", frame)

        if cv2.waitKey(30) & 0xFF == ord("q"):
            break

        time.sleep(0.03)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()