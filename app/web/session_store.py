"""In-memory store for active comparison sessions.

Everything here lives in process memory only -- nothing is written to a
database, nothing is sent anywhere. Each session owns one or two temporary
directories (extracted ZIPs / uploaded folder contents) which are cleaned
up when the session is explicitly deleted or when the process exits.
"""

from __future__ import annotations

import atexit
import shutil
import threading
import time
from dataclasses import dataclass, field

from app.core.comparator import CompareOptions
from app.models.comparison import ComparisonResult
from app.models.file_entry import FileEntry

_MAX_SESSIONS = 20  # local single-user tool: keep memory bounded


@dataclass
class Session:
    result: ComparisonResult
    left_manifest: dict[str, FileEntry]
    right_manifest: dict[str, FileEntry]
    temp_dirs: list[str]
    compare_options: CompareOptions
    created_at: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        atexit.register(self.cleanup_all)

    def put(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.result.comparison_id] = session
            self._evict_if_needed()

    def get(self, comparison_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(comparison_id)

    def delete(self, comparison_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(comparison_id, None)
        if session is None:
            return False
        self._cleanup_session(session)
        return True

    def _evict_if_needed(self) -> None:
        if len(self._sessions) <= _MAX_SESSIONS:
            return
        oldest_id = min(self._sessions, key=lambda k: self._sessions[k].created_at)
        session = self._sessions.pop(oldest_id)
        self._cleanup_session(session)

    @staticmethod
    def _cleanup_session(session: Session) -> None:
        for d in session.temp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def cleanup_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            self._cleanup_session(s)


store = SessionStore()
