import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from routier.contract import ContractError, validate_event
from routier.decision import assess
from routier.sources import count_gtfs_entities, fetch_sncf_service_alerts
from routier.store import save_snapshot, sources


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


class SourceSnapshotTests(unittest.TestCase):
    def test_counts_gtfs_entities_without_a_protobuf_dependency(self):
        # FeedMessage header (field 1), then two FeedEntity messages (field 2).
        payload = b"\x0a\x02v1\x12\x03one\x12\x03two"
        self.assertEqual(count_gtfs_entities(payload), 2)

    def test_latest_snapshot_is_persisted_by_source_and_checksum(self):
        snapshot = {
            "source_id": "sncf_gtfs_rt_service_alerts",
            "source": "SNCF Open Data",
            "format": "GTFS-RT service alerts",
            "source_url": "https://example.test/feed",
            "captured_at": "2026-08-22T10:00:00+00:00",
            "byte_size": 17,
            "entity_count": 2,
            "checksum": "abc123",
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "routier.db"
            self.assertTrue(save_snapshot(snapshot, path))
            snapshot["captured_at"] = "2026-08-22T10:01:00+00:00"
            self.assertFalse(save_snapshot(snapshot, path))
            self.assertEqual(sources(path), [snapshot])

    @patch("routier.sources.urlopen")
    def test_sncf_adapter_records_only_metadata(self, mocked_urlopen):
        class Response:
            def read(self):
                return b"\x0a\x02v1\x12\x03one"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        mocked_urlopen.return_value = Response()
        snapshot = fetch_sncf_service_alerts()
        self.assertEqual(snapshot["entity_count"], 1)
        self.assertEqual(snapshot["byte_size"], 9)
        self.assertEqual(len(snapshot["checksum"]), 16)
        self.assertNotIn("payload", snapshot)
