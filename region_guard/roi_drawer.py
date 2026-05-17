# region_guard/roi_drawer.py
import cv2
import json
import os

VIDEO_PATH = r"D:\App\savant-work\savant-work-main\test.mp4"
ROI_PATH = r"D:\App\savant-work\savant-work-main\region_guard\roi_config.json"
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


def draw_ui(frame, paused):
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

    # 左上角提示面板
    overlay = display.copy()
    cv2.rectangle(overlay, (10, 10), (510, 240), (0, 0, 0), -1)
    display = cv2.addWeighted(overlay, 0.55, display, 0.45, 0)

    play_status = "PAUSED - draw ROI now" if paused else "PLAYING - press SPACE to pause"

    tips = [
        "Task6 ROI Drawing Tool",
        play_status,
        "Left Click : add point",
        "Right Click: undo point",
        "F : save as Forbidden Zone",
        "A : save as Warning Zone",
        "C : clear current points",
        "R : clear all saved ROI",
        "S : save to roi_config.json",
        "SPACE : pause / continue",
        "Q : quit",
        f"Current points: {len(points)}",
        f"Saved ROI: {len(roi_list)}",
    ]

    y = 38
    for i, tip in enumerate(tips):
        color = (0, 255, 255) if i in (0, 1) else (255, 255, 255)
        cv2.putText(
            display,
            tip,
            (25, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            color,
            2,
        )
        y += 20

    return display


def add_roi(roi_type):
    global points

    if len(points) < 3:
        print("至少需要 3 个点才能形成 ROI")
        return

    name = input("请输入 ROI 名称（例如 A_warning / B_forbidden）：").strip()

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

def clear_current_points():
    global points
    points = []
    print("[清除] 当前正在绘制的点已清空")


def clear_all_rois():
    global roi_list, points
    confirm = input("确认清除所有已保存 ROI 吗？输入 yes 确认：").strip().lower()

    if confirm == "yes":
        roi_list = []
        points = []
        save_roi_config()
        print("[清除] 所有 ROI 已清空，并已写入配置文件")
    else:
        print("[取消] 未清除 ROI")


def load_existing_roi():
    if os.path.exists(ROI_PATH):
        try:
            with open(ROI_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
                roi_list.extend(old.get(CAMERA_ID, []))
            print(f"[加载已有 ROI] {ROI_PATH}")
        except Exception:
            print("[提示] 旧 ROI 文件读取失败，将重新创建")


def main():
    global current_frame

    load_existing_roi()

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print(f"无法打开视频：{VIDEO_PATH}")
        return

    cv2.namedWindow("Task6 ROI Drawer")
    cv2.setMouseCallback("Task6 ROI Drawer", mouse_callback)

    paused = False

    print("\n使用说明：")
    print("视频播放时，先按空格暂停")
    print("暂停后用鼠标左键添加 ROI 顶点")
    print("鼠标右键撤销上一个点")
    print("按 F：保存为 forbidden 禁区")
    print("按 A：保存为 warning 预警区")
    print("按 S：写入 roi_config.json")
    print("按 Q：退出\n")

    while True:
        if not paused:
            ret, frame = cap.read()

            if not ret:
                # 播放到结尾后自动回到开头
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            current_frame = frame

        if current_frame is None:
            continue

        display = draw_ui(current_frame, paused)
        cv2.imshow("Task6 ROI Drawer", display)

        key = cv2.waitKey(30) & 0xFF

        if key == ord(" "):
            paused = not paused
            print("已暂停，可以画 ROI" if paused else "继续播放")

        elif key == ord("f"):
            add_roi("forbidden")

        elif key == ord("a"):
            add_roi("warning")

        elif key == ord("c"):
            clear_current_points()

        elif key == ord("r"):
            clear_all_rois()

        elif key == ord("s"):
            save_roi_config()

        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()