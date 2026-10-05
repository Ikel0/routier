"""Per-visitor stores and request limits for the public demo.

The Render instance is shared by every visitor. Each browser session gets its
own short-lived SQLite file, seeded with the reference scenario, so nobody sees
what another visitor injected and nothing they send outlives the TTL.
"""

from __future__ import annotations

from collections import defaultdict, deque
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Callable

SESSION_PATTERN = re.compile(r"^[A-Za-z0-9-]{16,64}$")
SESSION_TTL_SECONDS = 3600
MAX_SESSIONS = 500


def default_session_root() -> Path:
    return Path(os.getenv("ROUTIER_SESSION_DIR", Path(tempfile.gettempdir()) / "routier-sessions"))


def _remove(path: Path) -> None:
    # SQLite in WAL mode leaves two companion files next to the database.
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        candidate.unlink(missing_ok=True)


class SessionStore:
    def __init__(
        self, root: Path, seed: Callable[[Path], None], ttl: float = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS, clock: Callable[[], float] = time.time,
    ):
        self.root = root
        self.seed = seed
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.clock = clock
        self._lock = threading.Lock()

    @staticmethod
    def valid(session_id: str | None) -> bool:
        return bool(session_id) and SESSION_PATTERN.fullmatch(session_id) is not None

    def _databases(self) -> list[Path]:
        return sorted(self.root.glob("*.db"), key=lambda item: item.stat().st_mtime)

    def _purge(self) -> None:
        cutoff = self.clock() - self.ttl
        databases = self._databases()
        for database in databases:
            if database.stat().st_mtime < cutoff:
                _remove(database)
        databases = self._databases()
        # Oldest sessions go first when the instance is crowded.
        for database in databases[: max(0, len(databases) - self.max_sessions + 1)]:
            _remove(database)

    def path_for(self, session_id: str) -> Path:
        if not self.valid(session_id):
            raise ValueError("invalid session identifier")
        path = self.root / f"{session_id}.db"
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                self._purge()
                self.seed(path)
            stamp = self.clock()
            os.utime(path, (stamp, stamp))
        return path

    def reset(self, session_id: str) -> Path:
        if not self.valid(session_id):
            raise ValueError("invalid session identifier")
        with self._lock:
            _remove(self.root / f"{session_id}.db")
        return self.path_for(session_id)


class RateLimiter:
    """Sliding one-minute window, kept in memory: a restart simply forgets it."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            if len(self._hits) > 10_000:
                for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                    del self._hits[stale]
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True
