"""Tiny event tap — runners emit, the eval server listens, CLI runs ignore.

emit() is a no-op unless a listener is installed. The server serializes runs
behind a lock, so one module-level listener is all we need. Emitting must
never break a run: listener errors are swallowed.
"""

from __future__ import annotations

from typing import Any, Callable

_listener: Callable[[str, dict], None] | None = None


def listen(fn: Callable[[str, dict], None]) -> None:
    global _listener
    _listener = fn


def unlisten() -> None:
    global _listener
    _listener = None


def emit(kind: str, **data: Any) -> None:
    if _listener is not None:
        try:
            _listener(kind, data)
        except Exception:
            pass
