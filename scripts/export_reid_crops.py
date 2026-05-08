from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Re-ID target crops from Savant metadata and video.")
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("runtime/crops"), type=Path)
    parser.add_argument("--uri-prefix", default="runtime/crops")
    parser.add_argument("--max-crops", default=50, type=int)
    parser.add_argument("--class-name", default="person")
    return parser.parse_args()


def load_crop_jobs(metadata_path: Path, class_name: str, max_crops: int) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    with metadata_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if len(jobs) >= max_crops:
                break
            if not line.strip():
                continue
            frame = json.loads(line)
            if frame.get("schema") != "VideoFrame":
                continue
            frame_num = int(frame.get("frame_num", 0))
            camera_id = str(frame.get("source_id", "unknown"))
            person_index = 0
            for obj in frame.get("metadata", {}).get("objects", []):
                if obj.get("label") != class_name:
                    continue
                bbox = obj.get("bbox", {})
                job = {
                    "frame_num": frame_num,
                    "camera_id": camera_id,
                    "object_id": int(obj.get("object_id", -1)),
                    "person_index": person_index,
                    "bbox": xc_bbox_to_ltwh(bbox),
                }
                jobs.append(job)
                person_index += 1
                if len(jobs) >= max_crops:
                    break
    return jobs


def xc_bbox_to_ltwh(bbox: Dict[str, Any]) -> Tuple[int, int, int, int]:
    width = float(bbox.get("width", 0))
    height = float(bbox.get("height", 0))
    left = float(bbox.get("xc", 0)) - width / 2
    top = float(bbox.get("yc", 0)) - height / 2
    return int(left), int(top), int(width), int(height)


def safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:80]


def crop_path(output_dir: Path, job: Dict[str, Any]) -> Path:
    camera_id = safe_path_part(str(job["camera_id"]))
    object_id = safe_path_part(str(job["object_id"]))
    frame_num = int(job["frame_num"])
    index = int(job["person_index"])
    digest = hashlib.sha1(f"{job['camera_id']}:{job['object_id']}:{frame_num}:{index}".encode()).hexdigest()[:8]
    return output_dir / camera_id / object_id / f"frame_{frame_num:08d}_{digest}.jpg"


def export_crops(video_path: Path, output_dir: Path, jobs: Iterable[Dict[str, Any]]) -> int:
    jobs_by_frame: Dict[int, List[Dict[str, Any]]] = {}
    for job in jobs:
        jobs_by_frame.setdefault(int(job["frame_num"]), []).append(job)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    written = 0
    for frame_num in sorted(jobs_by_frame):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ok, frame = cap.read()
        if not ok:
            continue
        frame_height, frame_width = frame.shape[:2]
        for job in jobs_by_frame[frame_num]:
            left, top, width, height = job["bbox"]
            x1 = max(0, left)
            y1 = max(0, top)
            x2 = min(frame_width, left + width)
            y2 = min(frame_height, top + height)
            if x2 <= x1 or y2 <= y1:
                continue
            path = crop_path(output_dir, job)
            path.parent.mkdir(parents=True, exist_ok=True)
            if cv2.imwrite(str(path), frame[y1:y2, x1:x2]):
                written += 1
    cap.release()
    return written


def main() -> None:
    args = parse_args()
    jobs = load_crop_jobs(args.metadata, args.class_name, args.max_crops)
    written = export_crops(args.video, args.output_dir, jobs)
    print(json.dumps({"jobs": len(jobs), "written": written}, ensure_ascii=False))
    if jobs and written == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

