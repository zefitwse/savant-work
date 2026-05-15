# task6/roi_manager.py
import json
import os
from typing import Dict, List


class ROIManager:
    def __init__(self, config_path: str = ""):
        if config_path:
            self.config_path = config_path
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.config_path = os.path.join(base_dir, "roi_config.json")
        self.roi_config = {}
        self.last_mtime = 0
        self.load()

    def load(self):
        if not os.path.exists(self.config_path):
            self.roi_config = {}
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.roi_config = json.load(f)

        self.last_mtime = os.path.getmtime(self.config_path)

    def reload_if_changed(self):
        if not os.path.exists(self.config_path):
            return

        current_mtime = os.path.getmtime(self.config_path)

        if current_mtime != self.last_mtime:
            print("[RegionGuard] ROI 配置已变化，重新加载")
            self.load()

    def get_rois(self, camera_id: str) -> List[dict]:
        self.reload_if_changed()
        return self.roi_config.get(camera_id, [])

    def get_all(self) -> Dict:
        self.reload_if_changed()
        return self.roi_config

    def update_camera_rois(self, camera_id: str, rois: List[dict]):
        self.roi_config[camera_id] = rois

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.roi_config, f, ensure_ascii=False, indent=2)

        self.last_mtime = os.path.getmtime(self.config_path)
