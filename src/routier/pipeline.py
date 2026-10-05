"""Testable delivery semantics shared by the Kafka worker and its tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from .contract import ContractError, validate_event


def trace_id_for(event: dict[str, Any]) -> str:
    event_id = str(event.get("event_id", "invalid"))
    digest = hashlib.sha256(f"routier:{event_id}".encode("utf-8")).hexdigest()[:20]
    return f"evt-{digest}"


def rejection_record(value: Any, reason: str) -> tuple[str, dict[str, Any]]:
    """Build the dead-letter key and payload for a rejected record.

    A crash between the dead-letter acknowledgement and the offset commit replays the
    record and publishes the rejection again. Both copies carry the same key and
    rejection_id, so a reader of the dead-letter topic can drop the second one.
    An invalid record may have no usable event_id: the key then falls back to a hash
    of its canonical JSON.
    """
    event_id = value.get("event_id") if isinstance(value, dict) else None
    if isinstance(event_id, str) and event_id.strip():
        key = event_id
    else:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        key = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    rejection_id = "rej-" + hashlib.sha256(f"{key}|{reason}".encode("utf-8")).hexdigest()[:20]
    payload = {
        "rejection_id": rejection_id,
        "event_key": key,
        "reason": reason,
        "worker": "routier-control",
        "event": value,
    }
    return key, payload


def process_message(
    value: dict[str, Any], deliver: Callable[[dict[str, Any]], None], reject: Callable[[dict[str, Any], str], None]
) -> str:
    """Deliver once or publish a durable rejection before the offset is committed."""
    try:
        event = validate_event(value)
    except ContractError as exc:
        reject(value, str(exc))
        return "rejected"
    deliver(event)
    return "delivered"
