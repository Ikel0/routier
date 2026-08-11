import unittest

from routier.contract import ContractError, validate_event
from routier.decision import assess


def event(**overrides):
    sample = {
        "event_id": "one", "vehicle_id": "R-1", "route_id": "M2", "recorded_at": "2026-08-11T09:00:00Z",
        "delay_seconds": 20, "occupancy_percent": 50, "status": "in_service", "latitude": 48.85, "longitude": 2.35,
    }
    sample.update(overrides)
    return sample


class ContractTests(unittest.TestCase):
    def test_rejects_bad_occupancy(self):
        with self.assertRaises(ContractError):
            validate_event(event(occupancy_percent=102))

    def test_critical_disruption_is_explained(self):
        result = assess(validate_event(event(status="disrupted", delay_seconds=940)))
        self.assertEqual(result["severity"], "critical")
        self.assertIn("service déclaré indisponible", result["reasons"])

    def test_healthy_service_has_no_alert(self):
        self.assertEqual(assess(validate_event(event()))["severity"], "none")
