from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coursework_savant.reid import (
    ReIDFeatureExtractor,
    ReIDSQLiteStore,
    decode_event_feature,
    event_stream_id,
    event_track_id,
)
from coursework_savant.telemetry import init_telemetry, start_span

try:
    from confluent_kafka import Consumer, Producer
except ImportError:  # allows local code review without Kafka client installed
    Consumer = None
    Producer = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consume Savant object events, build the one-hour Re-ID cache, and publish cross-camera matches."
    )
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--input-topic", default="deepstream.events")
    parser.add_argument("--output-topic", default="reid.events")
    parser.add_argument("--group-id", default="coursework-reid-service")
    parser.add_argument("--db-path", default=str(ROOT / "runtime" / "edge_control.db"))
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    parser.add_argument("--match-threshold", type=float, default=0.84)
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument("--max-messages", type=int, default=0, help="0 means run forever.")
    parser.add_argument("--poll-timeout", type=float, default=1.0)
    parser.add_argument("--print-events", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if Consumer is None or Producer is None:
        raise RuntimeError("confluent-kafka is required to run the Re-ID Kafka service.")

    init_telemetry("coursework-reid-service")
    reid_model_path = os.getenv("REID_MODEL_PATH")
    extractor = ReIDFeatureExtractor(model_path=Path(reid_model_path) if reid_model_path else None)
    store = ReIDSQLiteStore(
        Path(args.db_path),
        ttl_seconds=args.ttl_seconds,
        match_threshold=args.match_threshold,
    )
    consumer = Consumer(
        {
            "bootstrap.servers": args.bootstrap_servers,
            "group.id": args.group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    producer = Producer({"bootstrap.servers": args.bootstrap_servers})
    consumer.subscribe([args.input_topic])

    processed = 0
    try:
        while args.max_messages <= 0 or processed < args.max_messages:
            msg = consumer.poll(args.poll_timeout)
            if msg is None:
                continue
            if msg.error():
                print(f"Kafka error: {msg.error()}", file=sys.stderr)
                continue

            event = _decode_event(msg.value())
            if event is None:
                continue
            result = process_event(
                event=event,
                extractor=extractor,
                store=store,
                project_root=Path(args.project_root),
            )
            if result is None:
                continue

            payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
            key_value = result.get("global_id") or f"{result.get('stream_id')}:{result.get('track_id')}"
            key = str(key_value).encode("utf-8")
            producer.produce(args.output_topic, key=key, value=payload)
            producer.poll(0)
            if args.print_events:
                print(payload.decode("utf-8"))
            processed += 1
    finally:
        producer.flush(5)
        consumer.close()


def process_event(
    event: Dict[str, Any],
    extractor: ReIDFeatureExtractor,
    store: ReIDSQLiteStore,
    project_root: Path,
) -> Optional[Dict[str, Any]]:
    if (event.get("class") or event.get("class_name")) != "person":
        return None

    with start_span(
        "reid.event.consume",
        {
            "stream_id": event_stream_id(event),
            "track_id": event_track_id(event),
            "event_type": event.get("event_type"),
        },
    ):
        try:
            feature, crop_uri = decode_event_feature(event, project_root, extractor)
        except FileNotFoundError as exc:
            return {
                "msg_version": "1.0",
                "event_type": "reid_pending_crop",
                "stream_id": event_stream_id(event),
                "track_id": event_track_id(event),
                "reason": str(exc),
                "timestamp": event.get("timestamp"),
            }
        except Exception as exc:
            return {
                "msg_version": "1.0",
                "event_type": "reid_failed",
                "stream_id": event_stream_id(event),
                "track_id": event_track_id(event),
                "reason": str(exc),
                "timestamp": event.get("timestamp"),
            }

    with start_span(
        "reid.feature.match",
        {
            "stream_id": event_stream_id(event),
            "track_id": event_track_id(event),
            "feature.version": feature.version,
            "feature.dimension": feature.dimension,
        },
    ):
        return store.register_event(event, feature, crop_uri, feature_source="kafka_crop")


def _decode_event(payload: Optional[bytes]) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        print(f"Invalid Kafka JSON event: {exc}", file=sys.stderr)
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


if __name__ == "__main__":
    main()
