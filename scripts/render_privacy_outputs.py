from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coursework_savant.privacy_mask import PrivacyMasker


PRIMARY_LABELS = {
    "person",
    "car",
    "bicycle",
    "motorcycle",
    "bus",
    "truck",
    "vehicle",
    "foreign_object",
    "road_sign",
}

COLORS = {
    "person": (40, 220, 40),
    "vehicle": (255, 180, 40),
    "foreign_object": (40, 80, 255),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render admin raw OSD output and screenshots from Savant metadata."
    )
    parser.add_argument("--source", default="test.mp4")
    parser.add_argument("--metadata", default="runtime/savant-output/metadata.json")
    parser.add_argument("--raw-output", default="runtime/raw-output/video.mp4")
    parser.add_argument("--raw-shot", default=".codex_tmp/privacy_admin_raw_output.jpg")
    parser.add_argument("--masked-source", default="runtime/savant-output/video.mov")
    parser.add_argument("--masked-shot", default=".codex_tmp/privacy_operator_masked_output.jpg")
    parser.add_argument("--shot-frame", type=int, default=-1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_path = Path(args.source)
    metadata_path = Path(args.metadata)
    raw_output_path = Path(args.raw_output)
    raw_shot_path = Path(args.raw_shot)
    masked_source_path = Path(args.masked_source)
    masked_shot_path = Path(args.masked_shot)

    frames_meta = load_frame_metadata(metadata_path)
    render_raw_osd_video(source_path, frames_meta, raw_output_path)
    shot_frame = args.shot_frame if args.shot_frame >= 0 else choose_shot_frame(frames_meta)
    save_frame(raw_output_path, raw_shot_path, shot_frame)
    if masked_source_path.exists():
        save_frame(masked_source_path, masked_shot_path, shot_frame)

    print(f"raw_output={raw_output_path.resolve()}")
    print(f"raw_shot={raw_shot_path.resolve()}")
    if masked_source_path.exists():
        print(f"masked_shot={masked_shot_path.resolve()}")


def load_frame_metadata(path: Path) -> Dict[int, List[Dict[str, Any]]]:
    frames: Dict[int, List[Dict[str, Any]]] = {}
    if not path.exists():
        raise FileNotFoundError(path)

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        frame = json.loads(line)
        if frame.get("schema") != "VideoFrame":
            continue
        frame_num = int(frame.get("frame_num", 0))
        objects = [
            obj
            for obj in frame.get("metadata", {}).get("objects", [])
            if obj.get("label") in PRIMARY_LABELS and obj.get("model_name") != "auto"
        ]
        frames[frame_num] = objects
    return frames


def render_raw_osd_video(
    source_path: Path,
    frames_meta: Dict[int, List[Dict[str, Any]]],
    output_path: Path,
) -> None:
    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open source video: {source_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Cannot open video writer: {output_path}")

    frame_idx = 0
    source_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        objects = frames_meta.get(frame_idx, frames_meta.get(frame_idx % max(source_frame_count, 1), []))
        draw_objects(frame, objects)
        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()


def draw_objects(frame: Any, objects: Iterable[Dict[str, Any]]) -> None:
    for obj in objects:
        label = normalize_label(str(obj.get("label", "")))
        confidence = float(obj.get("confidence", 0.0))
        left, top, width, height = object_bbox_ltwh(obj)
        x1 = max(0, int(left))
        y1 = max(0, int(top))
        x2 = min(frame.shape[1] - 1, int(left + width))
        y2 = min(frame.shape[0] - 1, int(top + height))
        if x2 <= x1 or y2 <= y1:
            continue
        color = COLORS.get(label, (80, 220, 255))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        text = f"{label} {confidence:.2f}"
        text_y = max(20, y1 - 8)
        cv2.rectangle(frame, (x1, text_y - 20), (x1 + 190, text_y + 4), color, -1)
        cv2.putText(frame, text, (x1 + 4, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)


def choose_shot_frame(frames_meta: Dict[int, List[Dict[str, Any]]]) -> int:
    for frame_num in sorted(frames_meta):
        if any(obj.get("label") == "person" for obj in frames_meta[frame_num]):
            return frame_num
    return 0


def save_frame(video_path: Path, image_path: Path, frame_num: int) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video for screenshot: {video_path}")
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    target = min(max(0, frame_num), max(0, frame_count - 1)) if frame_count else frame_num
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Cannot read frame {target} from {video_path}")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(image_path), frame)


def object_bbox_ltwh(obj: Dict[str, Any]) -> Tuple[float, float, float, float]:
    bbox = obj.get("bbox", {})
    width = float(bbox.get("width", 0.0))
    height = float(bbox.get("height", 0.0))
    if "left" in bbox and "top" in bbox:
        return float(bbox["left"]), float(bbox["top"]), width, height
    xc = float(bbox.get("xc", 0.0))
    yc = float(bbox.get("yc", 0.0))
    return xc - width / 2.0, yc - height / 2.0, width, height


def normalize_label(label: str) -> str:
    if label in {"car", "bicycle", "motorcycle", "bus", "truck"}:
        return "vehicle"
    if label == "road_sign":
        return "foreign_object"
    return label


if __name__ == "__main__":
    main()
