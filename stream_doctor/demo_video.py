# task9/demo_video.py
import cv2
import numpy as np

from stream_doctor.metrics import diagnose_frame


OUT_PATH = "task9_vqd_demo.mp4"
W, H = 960, 540
FPS = 25
SECONDS_PER_CASE = 4


def put_label(frame, title, result):
    issues = result["issues"]
    status = result["status"]
    metrics = result["metrics"]

    text1 = f"Scene: {title}"
    text2 = f"Status: {status} | Issues: {issues}"
    text3 = f"Brightness: {metrics['brightness']:.1f} | Blur: {metrics['blur_score']:.1f} | Edge: {metrics['edge_score']:.1f}"

    cv2.rectangle(frame, (0, 0), (W, 120), (0, 0, 0), -1)
    cv2.putText(frame, text1, (30, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.putText(frame, text2, (30, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    cv2.putText(frame, text3, (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)


def make_base_frame(i):
    frame = np.ones((H, W, 3), dtype=np.uint8) * 180

    # 模拟工业场景背景
    cv2.rectangle(frame, (80, 180), (880, 450), (160, 160, 160), 3)
    cv2.line(frame, (80, 315), (880, 315), (120, 120, 120), 3)

    # 模拟移动目标
    x = 100 + (i * 6) % 700
    cv2.rectangle(frame, (x, 230), (x + 80, 390), (60, 60, 220), -1)
    cv2.circle(frame, (x + 40, 205), 28, (60, 60, 220), -1)

    return frame


def apply_dark(frame):
    return (frame * 0.18).astype(np.uint8)


def apply_blur(frame):
    return cv2.GaussianBlur(frame, (41, 41), 0)


def apply_occlusion(frame):
    blocked = frame.copy()
    cv2.rectangle(blocked, (240, 90), (720, 500), (20, 20, 20), -1)
    return blocked


def apply_signal_loss():
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    cv2.putText(frame, "SIGNAL LOST", (310, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    return frame


def main():
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(OUT_PATH, fourcc, FPS, (W, H))

    cases = [
        ("NORMAL", lambda f: f),
        ("DARK", apply_dark),
        ("BLUR", apply_blur),
        ("OCCLUSION", apply_occlusion),
        ("SIGNAL_LOSS", lambda f: apply_signal_loss()),
    ]

    total_frames = FPS * SECONDS_PER_CASE

    for title, func in cases:
        for i in range(total_frames):
            base = make_base_frame(i)
            frame = func(base)

            result = diagnose_frame(frame)

            if title == "SIGNAL_LOSS":
                result["status"] = "MAINTENANCE"
                result["issues"] = ["SIGNAL_LOSS"]

            put_label(frame, title, result)
            writer.write(frame)

    writer.release()
    print(f"演示视频已生成：{OUT_PATH}")


if __name__ == "__main__":
    main()