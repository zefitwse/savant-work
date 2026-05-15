# task6/roi_drawer.py
import cv2
import json
import os

VIDEO_PATH = "test.mp4"
ROI_PATH = "region_guard/roi_config.json"
CAMERA_ID = "cam01"

points = []
roi_list = []
current_frame = None


def save_roi_config():
    data = {CAMERA_ID: roi_list}

    with open(ROI_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[保存成功] ROI 已写入 {ROI_PATH}")


def mouse_callback(event, x, y, flags, param):
    global points

    if event == cv2.EVENT_LBUTTONDOWN:
        points.append([x, y])
        print(f"添加点：{x}, {y}")

    elif event == cv2.EVENT_RBUTTONDOWN:
        if points:
            points.pop()
            print("撤销上一个点")


def draw_ui(frame):
    display = frame.copy()

    # 已保存 ROI
    for roi in roi_list:
        pts = roi["points"]
        color = (0, 255, 0) if roi["type"] == "warning" else (0, 0, 255)

        for i in range(len(pts)):
            p1 = tuple(pts[i])
            p2 = tuple(pts[(i + 1) % len(pts)])
            cv2.line(display, p1, p2, color, 2)

        cv2.putText(
            display,
            f"{roi['name']} ({roi['type']})",
            tuple(pts[0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
        )

    # 正在绘制的 ROI
    for p in points:
        cv2.circle(display, tuple(p), 5, (255, 255, 0), -1)

    for i in range(len(points) - 1):
        cv2.line(display, tuple(points[i]), tuple(points[i + 1]), (255, 255, 0), 2)

    # 左上角半透明提示面板
    overlay = display.copy()
    cv2.rectangle(overlay, (10, 10), (470, 210), (0, 0, 0), -1)
    display = cv2.addWeighted(overlay, 0.55, display, 0.45, 0)

    tips = [
        "Task6 ROI Drawing Tool",
        "Left Click : add point",
        "Right Click: undo point",
        "F : save as Forbidden Zone",
        "A : save as Warning Zone",
        "S : save to roi_config.json",
        "Q : quit",
        f"Current points: {len(points)}",
        f"Saved ROI: {len(roi_list)}",
    ]

    y = 38
    for i, tip in enumerate(tips):
        color = (0, 255, 255) if i == 0 else (255, 255, 255)
        cv2.putText(
            display,
            tip,
            (25, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
        )
        y += 22

    return display


def add_roi(roi_type):
    global points

    if len(points) < 3:
        print("至少需要 3 个点才能形成 ROI")
        return

    name = input(f"请输入 ROI 名称（例如 A_warning / B_forbidden）：").strip()

    if not name:
        name = f"{roi_type}_{len(roi_list) + 1}"

    roi = {
        "name": name,
        "type": roi_type,
        "points": points.copy(),
    }

    roi_list.append(roi)
    points = []

    print(f"[添加 ROI] {roi}")


def main():
    global current_frame

    if os.path.exists(ROI_PATH):
        try:
            with open(ROI_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
                roi_list.extend(old.get(CAMERA_ID, []))
            print(f"[加载已有 ROI] {ROI_PATH}")
        except Exception:
            print("[提示] 旧 ROI 文件读取失败，将重新创建")

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print(f"无法打开视频：{VIDEO_PATH}")
        print("请把测试视频命名为 test.mp4，放到 D:\\work 目录下")
        return

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("无法读取视频第一帧")
        return

    current_frame = frame

    cv2.namedWindow("Task6 ROI Drawer")
    cv2.setMouseCallback("Task6 ROI Drawer", mouse_callback)

    print("\n使用说明：")
    print("鼠标左键：添加 ROI 顶点")
    print("鼠标右键：撤销上一个点")
    print("按 F：保存为 forbidden 禁区")
    print("按 A：保存为 warning 预警区")
    print("按 S：写入 roi_config.json")
    print("按 Q：退出\n")

    while True:
        display = draw_ui(current_frame)
        cv2.imshow("Task6 ROI Drawer", display)

        key = cv2.waitKey(20) & 0xFF

        if key == ord("f"):
            add_roi("forbidden")

        elif key == ord("a"):
            add_roi("warning")

        elif key == ord("s"):
            save_roi_config()

        elif key == ord("q"):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()