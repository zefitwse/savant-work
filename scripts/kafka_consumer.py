from __future__ import annotations

import argparse
import json

from confluent_kafka import Consumer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print DeepStream Kafka events.")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--topic", default="deepstream.events")
    parser.add_argument("--group-id", default="coursework-debug-consumer")
    parser.add_argument("--max-messages", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    consumer = Consumer(
        {
            "bootstrap.servers": args.bootstrap_servers,
            "group.id": args.group_id,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([args.topic])

    count = 0
    try:
        while count < args.max_messages:
            msg = consumer.poll(10)
            if msg is None:
                continue
            if msg.error():
                print(f"Kafka error: {msg.error()}")
                continue

            payload = msg.value().decode("utf-8")
            try:
                print(json.dumps(json.loads(payload), ensure_ascii=False))
            except json.JSONDecodeError:
                print(payload)
            count += 1
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
