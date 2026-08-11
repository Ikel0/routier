"""Publish the bundled synthetic event sample to the Kafka topic."""

from __future__ import annotations

import json
import os
from pathlib import Path

from kafka import KafkaProducer

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
    topic = os.getenv("KAFKA_TOPIC", "vehicle.telemetry.v1")
    producer = KafkaProducer(bootstrap_servers=bootstrap, value_serializer=lambda value: json.dumps(value).encode("utf-8"))
    for line in (ROOT / "data" / "demo_events.jsonl").read_text(encoding="utf-8").splitlines():
        producer.send(topic, json.loads(line))
    producer.flush()
    print("Published the Routier synthetic demo events.")


if __name__ == "__main__":
    main()
