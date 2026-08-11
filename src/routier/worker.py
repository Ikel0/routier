"""Kafka worker that validates events before handing them to the API."""

from __future__ import annotations

import json
import os
import time
from urllib.request import Request, urlopen

from kafka import KafkaConsumer, KafkaProducer

from .contract import ContractError, validate_event


def _post_to_api(event: dict) -> None:
    api_url = os.getenv("ROUTIER_API_URL", "http://localhost:8080")
    request = Request(
        f"{api_url}/api/events", data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urlopen(request, timeout=8):
        pass


def main() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", "vehicle.telemetry.v1")
    invalid_topic = os.getenv("KAFKA_INVALID_TOPIC", "vehicle.telemetry.invalid.v1")
    while True:
        try:
            consumer = KafkaConsumer(topic, bootstrap_servers=bootstrap, group_id="routier-control",
                                     auto_offset_reset="earliest", value_deserializer=lambda value: json.loads(value.decode("utf-8")))
            producer = KafkaProducer(bootstrap_servers=bootstrap, value_serializer=lambda value: json.dumps(value).encode("utf-8"))
            for message in consumer:
                try:
                    _post_to_api(validate_event(message.value))
                except ContractError as exc:
                    producer.send(invalid_topic, {"event": message.value, "reason": str(exc)})
                except Exception as exc:  # API failures leave the record available to the group on restart.
                    print(f"could not process message: {exc}")
                    break
        except Exception as exc:
            print(f"waiting for Kafka: {exc}")
        time.sleep(4)


if __name__ == "__main__":
    main()
