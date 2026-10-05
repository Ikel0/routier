"""HTTP control plane and operations dashboard for Routier."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
import re
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .contract import ContractError, validate_event
from .decision import assess
from .sessions import RateLimiter, SessionStore, default_session_root
from .sources import fetch_sncf_service_alerts
from .store import (
    acknowledge_alert,
    alerts,
    metrics,
    overview,
    recent_audit,
    record_audit,
    save_event,
    save_snapshot,
    sources,
)

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DATA = ROOT / "data" / "demo_events.jsonl"
STREAM = ROOT / "data" / "stream_events.jsonl"
MAX_BODY_BYTES = 64_000
TRACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
SESSION_HEADER = "X-Routier-Session"
# A stream run sends 8 messages at one every 1.6 s: 45 per minute leaves room
# for a reset and a second run, not for a flood.
EVENTS_PER_MINUTE_PER_SESSION = 45
WRITES_PER_MINUTE_PER_IP = 120
AUDIT_ROWS = 20


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _trace_id(event: object, request_id: str | None) -> str:
    if request_id and TRACE_PATTERN.fullmatch(request_id):
        return request_id
    if isinstance(event, dict) and isinstance(event.get("event_id"), str):
        digest = hashlib.sha256(f"routier:{event['event_id']}".encode("utf-8")).hexdigest()[:20]
        return f"evt-{digest}"
    return f"req-{uuid.uuid4().hex[:20]}"


def _origin(value: str | None) -> str:
    if value and re.fullmatch(r"[a-z0-9_.:-]{1,64}", value):
        return value
    return "direct-api"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def stream_messages() -> list[dict]:
    """Messages the « Lancer le flux » button sends, one at a time, to /api/events."""
    return _read_jsonl(STREAM)


def reference_messages() -> list[dict]:
    """The scenario every new session starts from: four telemetries, one replay, one off-contract message."""
    scenario = _read_jsonl(DATA)
    replay = dict(scenario[1])
    off_contract = {**scenario[3], "event_id": "demo-105", "vehicle_id": "R-412", "occupancy_percent": 104}
    return [*scenario, replay, off_contract]


def submit(raw_event: object, trace_id: str, origin: str, path: Path | None = None) -> tuple[HTTPStatus, dict]:
    """Validate, decide and record one message; a rejection is written to the audit, never dropped."""
    try:
        result = _ingest(raw_event, trace_id, origin, path)
        return (HTTPStatus.CREATED if result["status"] == "accepted" else HTTPStatus.OK), result
    except ContractError as exc:
        event_id = raw_event.get("event_id") if isinstance(raw_event, dict) and isinstance(raw_event.get("event_id"), str) else None
        recorded_at = raw_event.get("recorded_at") if isinstance(raw_event, dict) and isinstance(raw_event.get("recorded_at"), str) else None
        record_audit(trace_id, event_id, "rejected", origin, str(exc), recorded_at, path=path)
        return HTTPStatus.UNPROCESSABLE_ENTITY, {"status": "rejected", "trace_id": trace_id, "event_id": event_id, "error": str(exc)}


def seed_reference(path: Path) -> None:
    for message in reference_messages():
        submit(message, _trace_id(message, None), "demo-loader", path)


SESSIONS = SessionStore(default_session_root(), seed_reference)
SESSION_EVENTS = RateLimiter(EVENTS_PER_MINUTE_PER_SESSION)
IP_WRITES = RateLimiter(WRITES_PER_MINUTE_PER_IP)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _json(self, status: HTTPStatus, payload: dict | list) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ContractError("Content-Length must be an integer") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ContractError(f"request body must be at most {MAX_BODY_BYTES} bytes")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ContractError("body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ContractError("body must be a JSON object")
        return payload

    def _client_ip(self) -> str:
        # Adresse du visiteur posée par le proxy (True-Client-IP), sinon la première de X-Forwarded-For.
        true_client = self.headers.get("True-Client-IP", "").strip()
        if true_client:
            return true_client
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() or self.client_address[0]

    def _session(self) -> str | None:
        return self.headers.get(SESSION_HEADER)

    def _store(self) -> Path | None:
        """The visitor's own database, or the shared one for the worker and direct API calls."""
        session = self._session()
        if session is None:
            return None
        return SESSIONS.path_for(session)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "routier", "time": _now()})
            return
        if path == "/api/stream":
            self._json(HTTPStatus.OK, {"messages": stream_messages(), "interval_ms": 1600})
            return
        if not path.startswith("/api/") and path != "/ready":
            if path == "/":
                self.path = "/index.html"
            super().do_GET()
            return
        try:
            store = self._store()
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "identifiant de session invalide"})
            return
        if path == "/ready":
            current = metrics(store)
            self._json(HTTPStatus.OK, {
                "status": "ready", "database": "ok", "contract": current["contract"],
                "broker": "owned by the worker and not checked by the API",
            })
        elif path == "/api/overview":
            self._json(HTTPStatus.OK, overview(store))
        elif path == "/api/alerts":
            self._json(HTTPStatus.OK, {"items": alerts(store)})
        elif path == "/api/metrics":
            self._json(HTTPStatus.OK, metrics(store))
        elif path == "/api/audit":
            self._json(HTTPStatus.OK, {"items": recent_audit(AUDIT_ROWS, store)})
        elif path == "/api/sources":
            self._json(HTTPStatus.OK, {"sources": sources(store)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not IP_WRITES.allow(self._client_ip()):
            self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "Trop d'écritures depuis cette adresse en une minute. Réessaie dans un instant."})
            return
        try:
            store = self._store()
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "identifiant de session invalide"})
            return
        if path == "/api/reset":
            session = self._session()
            if not SESSIONS.valid(session):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "la remise à zéro demande une session"})
                return
            SESSIONS.reset(session)
            self._json(HTTPStatus.OK, {"status": "reset"})
            return
        if path == "/api/demo":
            outcomes = []
            for event in _read_jsonl(DATA):
                outcomes.append(_ingest(event, _trace_id(event, None), "demo-loader", store))
            self._json(HTTPStatus.CREATED, {
                "inserted": sum(item["status"] == "accepted" for item in outcomes),
                "duplicates": sum(item["status"] == "duplicate" for item in outcomes),
                "events": outcomes,
            })
            return
        if path == "/api/sources/sncf/sync":
            try:
                snapshot = fetch_sncf_service_alerts()
                snapshot["inserted"] = save_snapshot(snapshot, store)
                self._json(HTTPStatus.CREATED, snapshot)
            except (OSError, ValueError) as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "SNCF source unavailable", "detail": str(exc)})
            return
        if path.startswith("/api/alerts/") and path.endswith("/acknowledge"):
            event_id = unquote(path.removeprefix("/api/alerts/").removesuffix("/acknowledge").rstrip("/"))
            try:
                body = self._body()
                operator = str(body.get("operator", "")).strip()
                note = str(body.get("note", "")).strip()
                if not operator or len(operator) > 80:
                    raise ContractError("operator must be a non-empty string of at most 80 characters")
                if len(note) > 500:
                    raise ContractError("note must be at most 500 characters")
                acknowledgement = acknowledge_alert(event_id, operator, note, store)
                trace_id = _trace_id({"event_id": event_id}, self.headers.get("X-Request-ID"))
                record_audit(trace_id, event_id, "acknowledged", "ops-desk", operator, path=store)
                self._json(HTTPStatus.CREATED if acknowledgement["created"] else HTTPStatus.OK, acknowledgement)
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "alert not found"})
            except ContractError as exc:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
            except ValueError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        if path != "/api/events":
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        if not SESSION_EVENTS.allow(self._session() or self._client_ip()):
            self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": f"Plus de {EVENTS_PER_MINUTE_PER_SESSION} messages en une minute pour cette session. Réessaie dans un instant."})
            return
        raw_event: dict | object = {}
        trace_id = _trace_id(raw_event, self.headers.get("X-Request-ID"))
        origin = _origin(self.headers.get("X-Routier-Origin"))
        try:
            raw_event = self._body()
        except ContractError as exc:
            record_audit(trace_id, None, "rejected", origin, str(exc), path=store)
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"status": "rejected", "trace_id": trace_id, "error": str(exc)})
            return
        trace_id = _trace_id(raw_event, self.headers.get("X-Request-ID"))
        status, payload = submit(raw_event, trace_id, origin, store)
        self._json(status, payload)

    def log_message(self, format: str, *args) -> None:
        return


def _ingest(event: dict, trace_id: str, origin: str, path: Path | None = None) -> dict:
    valid = validate_event(event)
    verdict = assess(valid)
    persisted = save_event(valid, verdict, trace_id, origin, path)
    status = "accepted" if persisted["inserted"] else "duplicate"
    record_audit(trace_id, valid["event_id"], status, origin, recorded_at=valid["recorded_at"], path=path)
    return {
        "event_id": valid["event_id"],
        "trace_id": trace_id,
        "status": status,
        "ingested_at": persisted["ingested_at"],
        "decision": persisted["decision"],
    }


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    print(f"Routier running on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
