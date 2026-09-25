"""Small, explainable operational decision engine."""

from __future__ import annotations

from typing import Any

DECISION_VERSION = "1.0"


def assess(event: dict[str, Any]) -> dict[str, Any]:
    """Apply explicit service rules and return a stable, reviewable decision."""
    reasons: list[str] = []
    rule_ids: list[str] = []
    scores: list[int] = []
    delay = event["delay_seconds"]
    occupancy = event["occupancy_percent"]

    if event["status"] != "in_service":
        reasons.append("service déclaré indisponible")
        rule_ids.append("service.unavailable")
        scores.append(100)
    if delay >= 900:
        reasons.append("retard supérieur à 15 minutes")
        rule_ids.append("delay.critical")
        scores.append(80)
    elif delay >= 300:
        reasons.append("retard supérieur à 5 minutes")
        rule_ids.append("delay.watch")
        scores.append(45)
    if occupancy >= 95:
        reasons.append("surcharge critique")
        rule_ids.append("occupancy.critical")
        scores.append(65)
    elif occupancy >= 85:
        reasons.append("charge élevée")
        rule_ids.append("occupancy.watch")
        scores.append(30)

    priority_score = max(scores, default=0)
    severity = "critical" if priority_score >= 65 else "watch" if priority_score else "none"
    return {
        "severity": severity,
        "priority_score": priority_score,
        "reasons": reasons,
        "rule_ids": rule_ids,
        "decision_version": DECISION_VERSION,
    }
