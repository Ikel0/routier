"""Dependency-free API and dashboard server for the Routier prototype."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .contract import ContractError, validate_event
from .decision import assess
from .sources import fetch_sncf_service_alerts
from .store import alerts, overview, save_event, save_snapshot, sources

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DATA = ROOT / "data" / "demo_events.jsonl"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _json(self, status: int, payload: dict | list) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "routier"})
        elif path == "/api/overview":
            self._json(HTTPStatus.OK, overview())
        elif path == "/api/alerts":
            self._json(HTTPStatus.OK, alerts())
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
                outcomes.append(_ingest(json.loads(line)))
            self._json(HTTPStatus.CREATED, {"inserted": sum(item["inserted"] for item in outcomes), "events": outcomes})
            return
        if path == "/api/sources/sncf/sync":
            try:
                snapshot = fetch_sncf_service_alerts()
                snapshot["inserted"] = save_snapshot(snapshot)
                self._json(HTTPStatus.CREATED, snapshot)
            except (OSError, ValueError) as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "SNCF source unavailable", "detail": str(exc)})
            return
        if path != "/api/events":
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            event = json.loads(self.rfile.read(length))
            self._json(HTTPStatus.CREATED, _ingest(event))
        except json.JSONDecodeError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "body must be valid JSON"})
        except ContractError as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return


def _ingest(event: dict) -> dict:
    valid = validate_event(event)
    verdict = assess(valid)
    inserted = save_event(valid, verdict)
    return {"event_id": valid["event_id"], "inserted": inserted, "decision": verdict}


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    print(f"Routier running on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
