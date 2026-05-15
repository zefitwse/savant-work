import cv2
import numpy as np


def brightness(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def blur_score(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def edge_score(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    return float(np.mean(edges))

def diagnose_frame(
    frame,
    dark_threshold=40,
    blur_threshold=80,
    edge_threshold=5,
    baseline_frame=None,
    shift_threshold=35,
):
    issues = []

    b = brightness(frame)
    blur = blur_score(frame)
    edge = edge_score(frame)
    shift = shift_score(frame, baseline_frame)

    if b < dark_threshold:
        issues.append("DARK")

    if blur < blur_threshold:
        issues.append("BLUR")

    if edge < edge_threshold:
        issues.append("OCCLUSION")

    if baseline_frame is not None and shift > shift_threshold:
        issues.append("SHIFT")

    status = "OK" if not issues else "ABNORMAL"

    return {
        "status": status,
        "issues": issues,
        "metrics": {
            "brightness": b,
            "blur_score": blur,
            "edge_score": edge,
            "shift_score": shift,
        },
    }

def shift_score(frame, baseline_frame):
    """
    摄像头移位检测：
    用当前帧和基准帧做灰度差异。
    差异越大，说明画面整体变化越明显。
    """
    if baseline_frame is None:
        return 0.0

    gray_now = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray_base = cv2.cvtColor(baseline_frame, cv2.COLOR_BGR2GRAY)

    gray_now = cv2.resize(gray_now, (320, 180))
    gray_base = cv2.resize(gray_base, (320, 180))

    diff = cv2.absdiff(gray_now, gray_base)
    return float(np.mean(diff))