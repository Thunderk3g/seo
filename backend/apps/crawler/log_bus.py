"""In-memory log buffer for polling clients.

Replaces ``crawler-engine/app/core/log_bus.py`` (which fanned out from
worker threads to a WebSocket via ``asyncio.run_coroutine_threadsafe``).
Django's default WSGI stack has no event loop, so this version is a
thread-safe ring buffer that the polling DRF endpoint reads via
``poll(cursor)``.

Producers call ``post(msg)`` from any thread; consumers call
``poll(cursor)`` to receive every message appended since their last cursor.
The buffer is bounded so a never-polled crawler can't OOM the worker.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Deque, List, Optional, Tuple

_MAX_BUFFERED = 10_000  # ring buffer size; oldest messages drop when full

_lock = threading.Lock()
_buffer: Deque[Tuple[int, dict]] = deque(maxlen=_MAX_BUFFERED)
_next_seq: int = 1  # monotonic sequence id; consumers pass the last seen back


def post(msg: dict) -> None:
    """Append one log message to the buffer. Thread-safe."""
    global _next_seq
    if not isinstance(msg, dict):
        return
    with _lock:
        _buffer.append((_next_seq, msg))
        _next_seq += 1


def poll(cursor: Optional[int] = None, limit: int = 500) -> Tuple[List[dict], int]:
    """Return every message after ``cursor`` plus the new cursor.

    If ``cursor`` is ``None`` the caller is treated as fresh — they receive
    up to ``limit`` of the most recent messages so the dashboard renders
    immediately on first load.
    """
    with _lock:
        if not _buffer:
            return [], cursor if cursor is not None else 0
        if cursor is None:
            tail = list(_buffer)[-limit:]
        else:
            tail = [(seq, msg) for (seq, msg) in _buffer if seq > cursor][:limit]
        if not tail:
            return [], cursor if cursor is not None else _buffer[-1][0]
        new_cursor = tail[-1][0]
        return [msg for (_seq, msg) in tail], new_cursor


def head_cursor() -> int:
    """Return a cursor pointing at the latest message (no replay needed)."""
    with _lock:
        return _buffer[-1][0] if _buffer else 0


def reset() -> None:
    """Clear the buffer. Called by ``STATE.reset()`` between crawls."""
    global _next_seq
    with _lock:
        _buffer.clear()
        _next_seq = 1
