"""Kafka worker with manual commits and an idempotent HTTP sink."""

from __future__ import annotations

import json
import os
import time
from urllib.request import Request, urlopen

from kafka import KafkaConsumer, KafkaProducer

from .pipeline import process_message, rejection_record, trace_id_for


def _post_to_api(event: dict) -> None:
    api_url = os.getenv("ROUTIER_API_URL", "http://localhost:8080")
    request = Request(
        f"{api_url}/api/events",
        data=json.dumps(event).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": trace_id_for(event),
            "X-Routier-Origin": "kafka-worker",
        },
        method="POST",
    )
    with urlopen(request, timeout=8):
        pass


def main() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", "vehicle.telemetry.v1")
    invalid_topic = os.getenv("KAFKA_INVALID_TOPIC", "vehicle.telemetry.invalid.v1")
    while True:
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=bootstrap,
                group_id="routier-control",
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            )
            producer = KafkaProducer(
                bootstrap_servers=bootstrap,
                key_serializer=lambda key: key.encode("utf-8"),
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            )

            def reject(event: dict, reason: str) -> None:
                # Keyed by event_id: a replay after a crash republishes the same key and rejection_id.
                key, payload = rejection_record(event, reason)
                producer.send(invalid_topic, key=key, value=payload).get(timeout=10)

            for message in consumer:
                try:
                    process_message(message.value, _post_to_api, reject)
                    # Commit only after the API accepted or deduplicated the record, or the DLQ acknowledged it.
                    consumer.commit()
                except Exception as exc:
                    # No commit here: the record is replayed. The HTTP sink is idempotent on event_id.
                    print(f"processing paused, record will be replayed: {exc}")
                    break
        except Exception as exc:
            print(f"waiting for Kafka: {exc}")
        time.sleep(4)


if __name__ == "__main__":
    main()
