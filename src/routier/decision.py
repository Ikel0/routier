"""Small, explainable operational decision engine."""

from __future__ import annotations

from typing import Any


def assess(event: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    delay = event["delay_seconds"]
    occupancy = event["occupancy_percent"]
    if event["status"] != "in_service":
        reasons.append("service déclaré indisponible")
    if delay >= 900:
        reasons.append("retard supérieur à 15 minutes")
    elif delay >= 300:
        reasons.append("retard supérieur à 5 minutes")
    if occupancy >= 95:
        reasons.append("surcharge critique")
    elif occupancy >= 85:
        reasons.append("charge élevée")

    severity = "none"
    if event["status"] != "in_service" or delay >= 900 or occupancy >= 95:
        severity = "critical"
    elif delay >= 300 or occupancy >= 85:
        severity = "watch"
    return {"severity": severity, "reasons": reasons}
