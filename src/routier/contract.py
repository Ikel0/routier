"""Validation for the versioned vehicle telemetry contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

REQUIRED_FIELDS = {
    "event_id", "vehicle_id", "route_id", "recorded_at", "delay_seconds",
    "occupancy_percent", "status", "latitude", "longitude",
}
ALLOWED_STATUS = {"in_service", "disrupted", "out_of_service"}


class ContractError(ValueError):
    """Raised when an event cannot safely enter the operational store."""


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_FIELDS.difference(event)
    if missing:
        raise ContractError(f"missing required field(s): {', '.join(sorted(missing))}")
    if not all(isinstance(event[key], str) and event[key].strip() for key in ("event_id", "vehicle_id", "route_id")):
        raise ContractError("event_id, vehicle_id and route_id must be non-empty strings")
    try:
        datetime.fromisoformat(str(event["recorded_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("recorded_at must be an ISO-8601 timestamp") from exc
    if isinstance(event["delay_seconds"], bool) or not isinstance(event["delay_seconds"], (int, float)) or event["delay_seconds"] < 0:
        raise ContractError("delay_seconds must be a positive number or zero")
    if isinstance(event["occupancy_percent"], bool) or not isinstance(event["occupancy_percent"], (int, float)) or not 0 <= event["occupancy_percent"] <= 100:
        raise ContractError("occupancy_percent must be between 0 and 100")
    if event["status"] not in ALLOWED_STATUS:
        raise ContractError(f"status must be one of {', '.join(sorted(ALLOWED_STATUS))}")
    if not all(isinstance(event[key], (int, float)) for key in ("latitude", "longitude")):
        raise ContractError("latitude and longitude must be numbers")
    if not -90 <= event["latitude"] <= 90 or not -180 <= event["longitude"] <= 180:
        raise ContractError("coordinates are outside their valid ranges")
    return event
