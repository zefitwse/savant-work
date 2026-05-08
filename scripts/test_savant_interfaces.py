from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from control_store import ControlStore
from coursework_savant.crop_exporter import TargetCropExporter
from coursework_savant.event_builder import EventObject, SparseEventBuilder, fold_secondary_attributes
from coursework_savant.model_switcher import ModelSwitchWatcher
from coursework_savant.privacy_mask import PrivacyMasker, PrivacyPolicy
from coursework_savant.reid import ReIDFeatureExtractor, ReIDSQLiteStore
from coursework_savant.telemetry import init_telemetry, start_span


def test_event_builder() -> None:
    person = EventObject(
        camera_id="cam01",
        object_id=7,
        class_id=2,
        class_name="person",
        confidence=0.91,
        bbox={"left": 100, "top": 100, "width": 200, "height": 300},
    )
    helmet = EventObject(
        camera_id="cam01",
        object_id=9001,
        class_id=0,
        class_name="hardhat",
        confidence=0.84,
        bbox={"left": 140, "top": 120, "width": 40, "height": 40},
    )
    objects = fold_secondary_attributes([person], [helmet])
    assert objects[0].attributes["helmet"] == "hardhat"

    builder = SparseEventBuilder(ttl_frames=3, attribute_cooldown_frames=1)
    events = builder.update(1, objects)
    assert events[0]["event_type"] == "object_entered"
    assert events[0]["track_id"] == 7
    assert events[0]["attributes"]["helmet"] == "hardhat"
    assert events[0]["bbox"]["left"] == 100


def test_crop_exporter_and_gpu_ref_contract() -> None:
    output_dir = ROOT / ".codex_tmp" / "crop_export_test"
    if output_dir.exists():
        for item in output_dir.rglob("*.jpg"):
            item.unlink()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[20:80, 30:100] = [255, 128, 64]

    class FakeFrameMeta:
        source_id = "cam01"
        frame_num = 42
        width = 160
        height = 120
        batch_id = 0

    person = EventObject(
        camera_id="cam01",
        object_id=7,
        class_id=0,
        class_name="person",
        confidence=0.91,
        bbox={"left": 30, "top": 20, "width": 70, "height": 60},
    )
    exporter = TargetCropExporter(
        output_dir=str(output_dir),
        uri_prefix="runtime/crops",
        enabled=True,
        include_gpu_memory_ref=True,
    )
    exporter.enrich(frame, FakeFrameMeta(), [person])
    assert person.attributes["crop_status"] == "ok"
    assert person.attributes["crop_uri"].startswith("runtime/crops/cam01/7/")
    assert person.attributes["gpu_memory_ref"]["kind"] == "nvds_buffer_surface"
    assert "device_ptr_available" in person.attributes["gpu_memory_ref"]
    assert list(output_dir.rglob("*.jpg"))


def test_privacy_masker() -> None:
    masker = PrivacyMasker(
        PrivacyPolicy(
            enabled=True,
            masked_roles=["operator"],
            sensitive_classes=["face"],
            static_regions=[(1, 2, 3, 4)],
        )
    )
    boxes = masker.collect_mask_boxes(
        [
            {
                "class_name": "face",
                "bbox": {"left": 10, "top": 20, "width": 30, "height": 40},
            }
        ]
    )
    assert masker.should_mask("operator")
    assert not masker.should_mask("admin")
    assert boxes == [(1, 2, 3, 4), (10, 20, 30, 40)]

    class FakeBBox:
        left = 100
        top = 50
        width = 200
        height = 400

    class FakeObject:
        label = "person"
        bbox = FakeBBox()

    preview_boxes = masker.collect_preview_mask_boxes([FakeObject()])
    assert preview_boxes[-1] == (130, 50, 140, 144)


def test_control_store_and_hotswap_watcher() -> None:
    tmp_path = ROOT / ".codex_tmp" / "savant_interface_test"
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "edge_control.db"
    state_path = tmp_path / "model_state.json"
    for path in [db_path, state_path]:
        if path.exists():
            path.unlink()

    store = ControlStore(db_path)
    record = store.save_model_switch(
        node_id="edge-node-01",
        detector="pgie",
        engine_path="/models/day.engine",
        labels_path="/models/day.txt",
        reason="test",
    )
    assert store.latest_model_switch("edge-node-01").id == record.id

    state_path.write_text(
        json.dumps(
            {
                "id": record.id,
                "created_at": record.created_at,
                "payload": record.payload,
            }
        ),
        encoding="utf-8",
    )
    watcher = ModelSwitchWatcher(state_path)
    command = watcher.poll()
    assert command is not None
    assert command.engine_path == "/models/day.engine"
    assert watcher.poll() is None

    config = store.save_camera_config(
        camera_id="cam01",
        version="v1",
        roi=[{"name": "work_area", "polygon": [[0, 0], [1, 0], [1, 1]]}],
        thresholds={"person": 0.4},
        algorithm_params={"dedup_ttl_seconds": 3},
        privacy={"enabled": True},
    )
    assert store.latest_camera_config("cam01").id == config.id


def test_reid_cache_and_search_contract() -> None:
    from PIL import Image

    tmp_path = ROOT / ".codex_tmp" / "reid_interface_test"
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "edge_control.db"
    if db_path.exists():
        db_path.unlink()

    red_crop = tmp_path / "red.jpg"
    red_crop_2 = tmp_path / "red_2.jpg"
    blue_crop = tmp_path / "blue.jpg"
    Image.new("RGB", (64, 128), (210, 30, 30)).save(red_crop)
    Image.new("RGB", (64, 128), (205, 35, 35)).save(red_crop_2)
    Image.new("RGB", (64, 128), (20, 40, 210)).save(blue_crop)

    extractor = ReIDFeatureExtractor()
    store = ReIDSQLiteStore(db_path, ttl_seconds=3600, match_threshold=0.95)
    event_1 = {
        "stream_id": "cam01",
        "track_id": 7,
        "class": "person",
        "attributes": {"crop_uri": str(red_crop)},
    }
    event_2 = {
        "stream_id": "cam02",
        "track_id": 11,
        "class": "person",
        "attributes": {"crop_uri": str(red_crop_2)},
    }

    first = store.register_event(event_1, extractor.extract_from_path(red_crop), str(red_crop))
    second = store.register_event(event_2, extractor.extract_from_path(red_crop_2), str(red_crop_2))
    assert first["global_id"] == second["global_id"]
    assert first["msg_version"] == "1.0"
    assert second["stream_id"] == "cam02"
    assert second["event_type"] == "reid_matched"

    results = store.search(extractor.extract_from_path(blue_crop), top_k=2)
    assert len(results) == 2
    assert results[0]["stream_id"] in {"cam01", "cam02"}
    assert "similarity" in results[0]
    assert store.stats()["feature_count"] == 2


def test_telemetry_noop_contract() -> None:
    init_telemetry("coursework-test")
    with start_span("test.noop", {"ok": True}):
        pass


if __name__ == "__main__":
    test_event_builder()
    test_crop_exporter_and_gpu_ref_contract()
    test_privacy_masker()
    test_control_store_and_hotswap_watcher()
    test_reid_cache_and_search_contract()
    test_telemetry_noop_contract()
    print("savant interface tests passed")
