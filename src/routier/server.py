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
MAX_BODY_BYTES = 64_000
TRACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


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

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "routier", "time": _now()})
        elif path == "/ready":
            current = metrics()
            self._json(HTTPStatus.OK, {
                "status": "ready", "database": "ok", "contract": current["contract"],
                "broker": "owned by the worker and not checked by the API",
            })
        elif path == "/api/overview":
            self._json(HTTPStatus.OK, overview())
        elif path == "/api/alerts":
            self._json(HTTPStatus.OK, {"items": alerts()})
        elif path == "/api/metrics":
            self._json(HTTPStatus.OK, metrics())
        elif path == "/api/audit":
            self._json(HTTPStatus.OK, {"items": recent_audit()})
        elif path == "/api/sources":
            self._json(HTTPStatus.OK, {"sources": sources()})
        else:
            if path == "/":
                self.path = "/index.html"
            return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/demo":
            outcomes = []
            for line in DATA.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                outcomes.append(_ingest(event, _trace_id(event, None), "demo-loader"))
            self._json(HTTPStatus.CREATED, {
                "inserted": sum(item["status"] == "accepted" for item in outcomes),
                "duplicates": sum(item["status"] == "duplicate" for item in outcomes),
                "events": outcomes,
            })
            return
        if path == "/api/sources/sncf/sync":
            try:
                snapshot = fetch_sncf_service_alerts()
                snapshot["inserted"] = save_snapshot(snapshot)
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
                acknowledgement = acknowledge_alert(event_id, operator, note)
                trace_id = _trace_id({"event_id": event_id}, self.headers.get("X-Request-ID"))
                record_audit(trace_id, event_id, "acknowledged", "ops-desk", operator)
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
        raw_event: dict | object = {}
        trace_id = _trace_id(raw_event, self.headers.get("X-Request-ID"))
        origin = _origin(self.headers.get("X-Routier-Origin"))
        try:
            raw_event = self._body()
            trace_id = _trace_id(raw_event, self.headers.get("X-Request-ID"))
            result = _ingest(raw_event, trace_id, origin)
            self._json(HTTPStatus.CREATED if result["status"] == "accepted" else HTTPStatus.OK, result)
        except ContractError as exc:
            event_id = raw_event.get("event_id") if isinstance(raw_event, dict) and isinstance(raw_event.get("event_id"), str) else None
            recorded_at = raw_event.get("recorded_at") if isinstance(raw_event, dict) and isinstance(raw_event.get("recorded_at"), str) else None
            record_audit(trace_id, event_id, "rejected", origin, str(exc), recorded_at)
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"status": "rejected", "trace_id": trace_id, "error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return


def _ingest(event: dict, trace_id: str, origin: str) -> dict:
    valid = validate_event(event)
    verdict = assess(valid)
    persisted = save_event(valid, verdict, trace_id, origin)
    status = "accepted" if persisted["inserted"] else "duplicate"
    record_audit(trace_id, valid["event_id"], status, origin, recorded_at=valid["recorded_at"])
    return {
        "event_id": valid["event_id"],
        "trace_id": trace_id,
        "status": status,
        "ingested_at": persisted["ingested_at"],
        "decision": verdict,
    }


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    print(f"Routier running on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
