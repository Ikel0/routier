"""Adapters for public operational data sources used by Routier."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any
from urllib.request import Request, urlopen

SNCF_SERVICE_ALERTS_URL = "https://proxy.transport.data.gouv.fr/resource/sncf-gtfs-rt-service-alerts"


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(data):
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
        if shift > 63:
            break
    raise ValueError("invalid protobuf varint")


def count_gtfs_entities(payload: bytes) -> int:
    """Count FeedEntity records in a GTFS-RT protobuf without storing raw feed data."""
    position = 0
    entities = 0
    while position < len(payload):
        key, position = _read_varint(payload, position)
        field_number, wire_type = key >> 3, key & 0x07
        if wire_type == 0:
            _, position = _read_varint(payload, position)
        elif wire_type == 1:
            position += 8
        elif wire_type == 2:
            size, position = _read_varint(payload, position)
            if position + size > len(payload):
                raise ValueError("truncated protobuf field")
            if field_number == 2:
                entities += 1
            position += size
        elif wire_type == 5:
            position += 4
        else:
            raise ValueError("unsupported protobuf wire type")
    return entities


def fetch_sncf_service_alerts() -> dict[str, Any]:
    request = Request(
        SNCF_SERVICE_ALERTS_URL,
        headers={"User-Agent": "Ikel-Routier/1.0 (+https://github.com/Ikel0/routier)", "Accept": "application/x-protobuf"},
    )
    with urlopen(request, timeout=12) as response:
        payload = response.read()
    return {
        "source_id": "sncf_gtfs_rt_service_alerts",
        "source": "SNCF Open Data",
        "format": "GTFS-RT service alerts",
        "source_url": SNCF_SERVICE_ALERTS_URL,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "byte_size": len(payload),
        "entity_count": count_gtfs_entities(payload),
        "checksum": hashlib.sha256(payload).hexdigest()[:16],
    }
