import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from routier.contract import ContractError, validate_event
from routier.decision import assess
from routier.pipeline import process_message, trace_id_for
from routier.sources import count_gtfs_entities, fetch_sncf_service_alerts
from routier.store import acknowledge_alert, metrics, overview, record_audit, save_event, save_snapshot, sources


def event(**overrides):
    sample = {
        "event_id": "one", "event_type": "vehicle.telemetry", "schema_version": "1.0",
        "vehicle_id": "R-1", "route_id": "M2", "recorded_at": "2026-08-11T09:00:00Z",
        "delay_seconds": 20, "occupancy_percent": 50, "status": "in_service", "latitude": 48.85,
        "longitude": 2.35,
    }
    sample.update(overrides)
    return sample


class ContractTests(unittest.TestCase):
    def test_rejects_bad_occupancy(self):
        with self.assertRaises(ContractError):
            validate_event(event(occupancy_percent=102))

    def test_rejects_unknown_contract_version(self):
        with self.assertRaisesRegex(ContractError, "schema_version"):
            validate_event(event(schema_version="2.0"))

    def test_rejects_timestamp_without_timezone(self):
        with self.assertRaisesRegex(ContractError, "timezone"):
            validate_event(event(recorded_at="2026-08-11T09:00:00"))

    def test_critical_disruption_is_explained(self):
        result = assess(validate_event(event(status="disrupted", delay_seconds=940)))
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["priority_score"], 100)
        self.assertIn("service.unavailable", result["rule_ids"])

    def test_healthy_service_has_no_alert(self):
        self.assertEqual(assess(validate_event(event()))["severity"], "none")


class DeliveryTests(unittest.TestCase):
    def test_valid_message_is_delivered_once_to_the_sink(self):
        delivered, rejected = [], []
        outcome = process_message(event(), delivered.append, lambda payload, reason: rejected.append((payload, reason)))
        self.assertEqual(outcome, "delivered")
        self.assertEqual(len(delivered), 1)
        self.assertFalse(rejected)
        self.assertTrue(trace_id_for(event()).startswith("evt-"))

    def test_invalid_message_is_sent_to_the_dead_letter_path(self):
        delivered, rejected = [], []
        outcome = process_message(event(schema_version="bad"), delivered.append, lambda payload, reason: rejected.append((payload, reason)))
        self.assertEqual(outcome, "rejected")
        self.assertFalse(delivered)
        self.assertIn("schema_version", rejected[0][1])


class OperationalStoreTests(unittest.TestCase):
    def test_idempotency_audit_and_acknowledgement_are_visible(self):
        critical = event(event_id="critical-1", status="disrupted", delay_seconds=990)
        verdict = assess(validate_event(critical))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "routier.db"
            first = save_event(critical, verdict, "evt-first", "test", path)
            record_audit("evt-first", "critical-1", "accepted", "test", path=path)
            duplicate = save_event(critical, verdict, "evt-first", "test", path)
            record_audit("evt-first", "critical-1", "duplicate", "test", path=path)
            self.assertTrue(first["inserted"])
            self.assertFalse(duplicate["inserted"])

            before_ack = overview(path)
            self.assertEqual(before_ack["open_alerts"], 1)
            acknowledgement = acknowledge_alert("critical-1", "ops-demo", "prise en charge", path)
            self.assertTrue(acknowledgement["created"])
            after_ack = overview(path)
            self.assertEqual(after_ack["open_alerts"], 0)
            report = metrics(path)
            self.assertEqual(report["accepted"], 1)
            self.assertEqual(report["duplicates"], 1)
            self.assertEqual(report["acknowledged"], 1)


    def test_replay_with_changed_content_returns_the_stored_decision(self):
        healthy = event(event_id="replayed-1")
        changed = event(event_id="replayed-1", status="disrupted", delay_seconds=990)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "routier.db"
            save_event(healthy, assess(validate_event(healthy)), "evt-a", "test", path)
            replay = save_event(changed, assess(validate_event(changed)), "evt-b", "test", path)
            self.assertFalse(replay["inserted"])
            self.assertEqual(replay["decision"]["severity"], assess(validate_event(healthy))["severity"])
            self.assertNotEqual(replay["decision"]["severity"], assess(validate_event(changed))["severity"])


class SourceSnapshotTests(unittest.TestCase):
    def test_counts_gtfs_entities_without_a_protobuf_dependency(self):
        payload = b"\x0a\x02v1\x12\x03one\x12\x03two"
        self.assertEqual(count_gtfs_entities(payload), 2)

    def test_latest_snapshot_is_persisted_by_source_and_checksum(self):
        snapshot = {
            "source_id": "sncf_gtfs_rt_service_alerts", "source": "SNCF Open Data",
            "format": "GTFS-RT service alerts", "source_url": "https://example.test/feed",
            "captured_at": "2026-08-22T10:00:00+00:00", "byte_size": 17, "entity_count": 2,
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
