"""Testable delivery semantics shared by the Kafka worker and its tests."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from .contract import ContractError, validate_event


def trace_id_for(event: dict[str, Any]) -> str:
    event_id = str(event.get("event_id", "invalid"))
    digest = hashlib.sha256(f"routier:{event_id}".encode("utf-8")).hexdigest()[:20]
    return f"evt-{digest}"


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
