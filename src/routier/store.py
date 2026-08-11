"""SQLite persistence; deliberately small and inspectable for the prototype."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


def database_path() -> Path:
    base = Path(os.getenv("ROUTIER_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "routier.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL, route_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL, delay_seconds REAL NOT NULL,
            occupancy_percent REAL NOT NULL, status TEXT NOT NULL,
            latitude REAL NOT NULL, longitude REAL NOT NULL,
            severity TEXT NOT NULL, reasons TEXT NOT NULL
        )"""
    )
    return conn


def save_event(event: dict[str, Any], verdict: dict[str, Any], path: Path | None = None) -> bool:
    with connect(path) as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event["event_id"], event["vehicle_id"], event["route_id"], event["recorded_at"],
             event["delay_seconds"], event["occupancy_percent"], event["status"],
             event["latitude"], event["longitude"], verdict["severity"], json.dumps(verdict["reasons"])),
        )
        return cursor.rowcount == 1


def overview(path: Path | None = None) -> dict[str, Any]:
    with connect(path) as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"]
        active = conn.execute("SELECT COUNT(*) AS count FROM events WHERE severity != 'none'").fetchone()["count"]
        routes = conn.execute("SELECT COUNT(DISTINCT route_id) AS count FROM events").fetchone()["count"]
        rows = conn.execute("SELECT * FROM events ORDER BY recorded_at DESC LIMIT 12").fetchall()
    events = [dict(row) for row in rows]
    for event in events:
        event["reasons"] = json.loads(event["reasons"])
    return {"total_events": total, "open_alerts": active, "routes_seen": routes, "events": events}


def alerts(path: Path | None = None) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute("SELECT * FROM events WHERE severity != 'none' ORDER BY recorded_at DESC").fetchall()
    output = [dict(row) for row in rows]
    for alert in output:
        alert["reasons"] = json.loads(alert["reasons"])
    return output
