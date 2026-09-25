"""Validation for the versioned vehicle telemetry contract."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any

EVENT_TYPE = "vehicle.telemetry"
SCHEMA_VERSION = "1.0"
REQUIRED_FIELDS = {
    "event_id", "event_type", "schema_version", "vehicle_id", "route_id", "recorded_at",
    "delay_seconds", "occupancy_percent", "status", "latitude", "longitude",
}
ALLOWED_STATUS = {"in_service", "disrupted", "out_of_service"}


class ContractError(ValueError):
    """Raised when an event cannot safely enter the operational store."""


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate the immutable business payload before any side effect occurs."""
    if not isinstance(event, dict):
        raise ContractError("event must be a JSON object")
    missing = REQUIRED_FIELDS.difference(event)
    if missing:
        raise ContractError(f"missing required field(s): {', '.join(sorted(missing))}")
    if event["event_type"] != EVENT_TYPE:
        raise ContractError(f"event_type must be {EVENT_TYPE}")
    if event["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("event_id", "vehicle_id", "route_id"):
        value = event[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ContractError(f"{key} must be a non-empty string of at most 128 characters")
    try:
        recorded_at = datetime.fromisoformat(str(event["recorded_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("recorded_at must be an ISO-8601 timestamp") from exc
    if recorded_at.tzinfo is None:
        raise ContractError("recorded_at must include a timezone")
    if not _is_finite_number(event["delay_seconds"]) or event["delay_seconds"] < 0:
        raise ContractError("delay_seconds must be a finite positive number or zero")
    if not _is_finite_number(event["occupancy_percent"]) or not 0 <= event["occupancy_percent"] <= 100:
        raise ContractError("occupancy_percent must be a finite number between 0 and 100")
    if event["status"] not in ALLOWED_STATUS:
        raise ContractError(f"status must be one of {', '.join(sorted(ALLOWED_STATUS))}")
    if not all(_is_finite_number(event[key]) for key in ("latitude", "longitude")):
        raise ContractError("coordinates must be finite numbers")
    if not -90 <= event["latitude"] <= 90 or not -180 <= event["longitude"] <= 180:
        raise ContractError("coordinates are outside their valid ranges")
    return dict(event)
