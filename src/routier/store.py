"""Durable operational store with an explicit audit trail for Routier."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def database_path() -> Path:
    base = Path(os.getenv("ROUTIER_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "routier.db"


def _ensure_column(conn: sqlite3.Connection, name: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if name not in columns:
        conn.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL, route_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL, delay_seconds REAL NOT NULL,
            occupancy_percent REAL NOT NULL, status TEXT NOT NULL,
            latitude REAL NOT NULL, longitude REAL NOT NULL,
            severity TEXT NOT NULL, reasons TEXT NOT NULL,
            decision_version TEXT NOT NULL DEFAULT '1.0',
            rule_ids TEXT NOT NULL DEFAULT '[]', priority_score INTEGER NOT NULL DEFAULT 0,
            trace_id TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT 'api',
            ingested_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ingestion_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL, event_id TEXT, outcome TEXT NOT NULL,
            origin TEXT NOT NULL, reason TEXT, recorded_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alert_acknowledgements (
            event_id TEXT PRIMARY KEY REFERENCES events(event_id),
            operator TEXT NOT NULL, note TEXT NOT NULL, acknowledged_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity, recorded_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON ingestion_audit(created_at DESC);
        CREATE TABLE IF NOT EXISTS feed_snapshots (
            source_id TEXT NOT NULL, captured_at TEXT NOT NULL, source TEXT NOT NULL,
            format TEXT NOT NULL, source_url TEXT NOT NULL, byte_size INTEGER NOT NULL,
            entity_count INTEGER NOT NULL, checksum TEXT NOT NULL,
            PRIMARY KEY(source_id, checksum)
        );
        """
    )
    # Upgrade existing demo databases without asking users to throw away their state.
    _ensure_column(conn, "decision_version", "TEXT NOT NULL DEFAULT '1.0'")
    _ensure_column(conn, "rule_ids", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "priority_score", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "trace_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "origin", "TEXT NOT NULL DEFAULT 'api'")
    _ensure_column(conn, "ingested_at", "TEXT NOT NULL DEFAULT ''")
    return conn


def save_event(
    event: dict[str, Any], verdict: dict[str, Any], trace_id: str, origin: str, path: Path | None = None
) -> dict[str, Any]:
    ingested_at = now()
    with closing(connect(path)) as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO events (
                event_id, vehicle_id, route_id, recorded_at, delay_seconds, occupancy_percent,
                status, latitude, longitude, severity, reasons, decision_version, rule_ids,
                priority_score, trace_id, origin, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["event_id"], event["vehicle_id"], event["route_id"], event["recorded_at"],
                event["delay_seconds"], event["occupancy_percent"], event["status"], event["latitude"],
                event["longitude"], verdict["severity"], json.dumps(verdict["reasons"]),
                verdict["decision_version"], json.dumps(verdict["rule_ids"]), verdict["priority_score"],
                trace_id, origin, ingested_at,
            ),
        )
        conn.commit()
        return {"inserted": cursor.rowcount == 1, "ingested_at": ingested_at}


def record_audit(
    trace_id: str, event_id: str | None, outcome: str, origin: str, reason: str | None = None,
    recorded_at: str | None = None, path: Path | None = None,
) -> None:
    with closing(connect(path)) as conn:
        conn.execute(
            """INSERT INTO ingestion_audit(trace_id, event_id, outcome, origin, reason, recorded_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, event_id, outcome, origin, reason, recorded_at, now()),
        )
        conn.commit()


def _event_rows(conn: sqlite3.Connection, limit: int, only_open: bool = False) -> list[sqlite3.Row]:
    where = "WHERE e.severity != 'none' AND a.event_id IS NULL" if only_open else ""
    return conn.execute(
        f"""SELECT e.*, a.operator AS acknowledged_by, a.note AS acknowledgement_note,
        a.acknowledged_at FROM events e
        LEFT JOIN alert_acknowledgements a ON a.event_id = e.event_id
        {where}
        ORDER BY e.priority_score DESC, e.recorded_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def _serialize_event(row: sqlite3.Row) -> dict[str, Any]:
    event = dict(row)
    event["reasons"] = json.loads(event["reasons"])
    event["rule_ids"] = json.loads(event["rule_ids"])
    return event


def overview(path: Path | None = None) -> dict[str, Any]:
    with closing(connect(path)) as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"]
        open_alerts = conn.execute(
            """SELECT COUNT(*) AS count FROM events e LEFT JOIN alert_acknowledgements a
            ON a.event_id = e.event_id WHERE e.severity != 'none' AND a.event_id IS NULL"""
        ).fetchone()["count"]
        routes = conn.execute("SELECT COUNT(DISTINCT route_id) AS count FROM events").fetchone()["count"]
        rows = _event_rows(conn, limit=12)
    return {"total_events": total, "open_alerts": open_alerts, "routes_seen": routes, "events": [_serialize_event(row) for row in rows]}


def alerts(path: Path | None = None) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        rows = _event_rows(conn, limit=50, only_open=True)
    return [_serialize_event(row) for row in rows]


def acknowledge_alert(event_id: str, operator: str, note: str, path: Path | None = None) -> dict[str, Any]:
    with closing(connect(path)) as conn:
        event = conn.execute("SELECT event_id, severity FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if event is None:
            raise KeyError("alert not found")
        if event["severity"] == "none":
            raise ValueError("only an alert can be acknowledged")
        existing = conn.execute("SELECT * FROM alert_acknowledgements WHERE event_id = ?", (event_id,)).fetchone()
        if existing is not None:
            return {**dict(existing), "created": False}
        acknowledgement = {"event_id": event_id, "operator": operator, "note": note, "acknowledged_at": now()}
        conn.execute(
            """INSERT INTO alert_acknowledgements(event_id, operator, note, acknowledged_at)
            VALUES (:event_id, :operator, :note, :acknowledged_at)""",
            acknowledgement,
        )
        conn.commit()
        return {**acknowledgement, "created": True}


def metrics(path: Path | None = None) -> dict[str, Any]:
    with closing(connect(path)) as conn:
        grouped = conn.execute("SELECT outcome, COUNT(*) AS count FROM ingestion_audit GROUP BY outcome").fetchall()
        outcomes = {row["outcome"]: row["count"] for row in grouped}
        latest = conn.execute("SELECT created_at FROM ingestion_audit ORDER BY id DESC LIMIT 1").fetchone()
        acknowledged = conn.execute("SELECT COUNT(*) AS count FROM alert_acknowledgements").fetchone()["count"]
        source = conn.execute("SELECT source, captured_at, checksum FROM feed_snapshots ORDER BY captured_at DESC LIMIT 1").fetchone()
    return {
        "delivery_semantics": "at_least_once_with_idempotent_sink",
        "contract": "vehicle.telemetry.v1.0",
        "dead_letter_topic": os.getenv("KAFKA_INVALID_TOPIC", "vehicle.telemetry.invalid.v1"),
        "accepted": outcomes.get("accepted", 0),
        "duplicates": outcomes.get("duplicate", 0),
        "rejected": outcomes.get("rejected", 0),
        "acknowledged": acknowledged,
        "last_activity_at": latest["created_at"] if latest else None,
        "latest_source": dict(source) if source else None,
    }


def recent_audit(limit: int = 12, path: Path | None = None) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        rows = conn.execute(
            """SELECT trace_id, event_id, outcome, origin, reason, recorded_at, created_at
            FROM ingestion_audit ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_snapshot(snapshot: dict[str, Any], path: Path | None = None) -> bool:
    with closing(connect(path)) as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO feed_snapshots
            (source_id, captured_at, source, format, source_url, byte_size, entity_count, checksum)
            VALUES (:source_id, :captured_at, :source, :format, :source_url, :byte_size, :entity_count, :checksum)""",
            snapshot,
        )
        is_new = cursor.rowcount == 1
        if not is_new:
            conn.execute(
                """UPDATE feed_snapshots
                SET captured_at = :captured_at, source = :source, format = :format,
                    source_url = :source_url, byte_size = :byte_size, entity_count = :entity_count
                WHERE source_id = :source_id AND checksum = :checksum""",
                snapshot,
            )
        conn.commit()
        return is_new


def sources(path: Path | None = None) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        rows = conn.execute(
            """SELECT * FROM feed_snapshots
            WHERE rowid IN (SELECT MAX(rowid) FROM feed_snapshots GROUP BY source_id)
            ORDER BY captured_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]
