"""Multi-key pool for rate-limited LLM providers (Groq, xAI, etc.).

Why this exists
================
Free-tier Groq Cloud gives each API key its own TPM (tokens per minute)
budget — currently ~20–30k TPM. A single agent fleet run hits this in
seconds. Operators with N free keys want to use them as if they were
one logical pool with N× the throughput.

Behaviour
---------
* Round-robin allocation across non-cooling keys.
* 429 / TPM-exhausted responses → exponential backoff on the offending
  key (60 s, 120 s, 240 s, … capped at 5 min); pool advances to the
  next key transparently.
* If *every* key is cooling, the pool raises with the time to the
  soonest-available key so the caller can sleep precisely.
* Thread-safe — agent fleet runs concurrently.

Drop-in
-------
`GroqKeyPool` is the only public symbol. Callers acquire a key for
each request, report the outcome, and never see the underlying state.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class _KeyState:
    api_key: str
    cooldown_until: float = 0.0      # epoch sec; key idle until then
    consecutive_429s: int = 0
    total_calls: int = 0
    total_429s: int = 0
    last_success_at: float = 0.0
    last_429_at: float = 0.0


class PoolExhaustedError(RuntimeError):
    """All keys are cooling. Carries ``wait_seconds`` so the caller can
    sleep precisely until at least one key is available."""

    def __init__(self, wait_seconds: float, message: str = "") -> None:
        super().__init__(message or f"all keys cooling for {wait_seconds:.1f}s")
        self.wait_seconds = wait_seconds


class GroqKeyPool:
    """Round-robin pool with per-key exponential cooldown.

    Usage:

        pool = GroqKeyPool([k1, k2, k3])
        key = pool.acquire()
        try:
            response = call_groq(key, ...)
            pool.report_success(key)
        except Exception as exc:
            if is_rate_limit(exc):
                pool.report_429(key)
            raise

    Concurrency: every method holds an internal Lock for the duration
    of state mutation. Acquire is O(N) worst-case where N is keys; for
    the typical N≤16 this is irrelevant.
    """

    def __init__(
        self,
        keys: list[str],
        *,
        base_cooldown_sec: float = 60.0,
        max_cooldown_sec: float = 300.0,
    ) -> None:
        cleaned = [k.strip() for k in keys if k and k.strip()]
        if not cleaned:
            raise RuntimeError(
                "GroqKeyPool: no keys configured. Set GROQ_API_KEYS=k1,k2,...",
            )
        # Dedupe while preserving order so the operator's intent in
        # GROQ_API_KEYS is honoured (first key gets the first request).
        seen: set[str] = set()
        unique = [k for k in cleaned if not (k in seen or seen.add(k))]
        self._states = [_KeyState(api_key=k) for k in unique]
        self._base_cooldown = float(base_cooldown_sec)
        self._max_cooldown = float(max_cooldown_sec)
        self._idx = itertools.cycle(range(len(self._states)))
        self._lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────

    def acquire(self) -> str:
        """Return the next available API key.

        Raises :class:`PoolExhaustedError` with ``wait_seconds`` set
        when every key is in cooldown.
        """
        with self._lock:
            now = time.time()
            # Try up to N candidates so we don't infinite-loop when every
            # key is cooling (worst-case it touches each key once).
            for _ in range(len(self._states)):
                i = next(self._idx)
                state = self._states[i]
                if state.cooldown_until <= now:
                    state.total_calls += 1
                    return state.api_key
            # All cooling — return the soonest-available wait time.
            soonest = min(s.cooldown_until for s in self._states)
            wait = max(0.0, soonest - now)
            log.warning(
                "GroqKeyPool exhausted: %d/%d keys cooling, next free in %.1fs",
                sum(1 for s in self._states if s.cooldown_until > now),
                len(self._states),
                wait,
            )
            raise PoolExhaustedError(wait)

    def report_429(self, api_key: str) -> None:
        """Mark a key as rate-limited. Cooldown grows exponentially
        per consecutive 429, capped at ``max_cooldown_sec``."""
        with self._lock:
            now = time.time()
            for state in self._states:
                if state.api_key == api_key:
                    state.consecutive_429s += 1
                    state.total_429s += 1
                    state.last_429_at = now
                    delay = min(
                        self._base_cooldown * (2 ** (state.consecutive_429s - 1)),
                        self._max_cooldown,
                    )
                    state.cooldown_until = now + delay
                    log.info(
                        "GroqKeyPool: key ...%s cooling for %.0fs (consecutive_429s=%d)",
                        state.api_key[-6:],
                        delay,
                        state.consecutive_429s,
                    )
                    return

    def report_success(self, api_key: str) -> None:
        """Reset a key's consecutive-429 counter after a successful call."""
        with self._lock:
            now = time.time()
            for state in self._states:
                if state.api_key == api_key:
                    state.consecutive_429s = 0
                    state.last_success_at = now
                    return

    def stats(self) -> list[dict[str, Any]]:
        """Snapshot of every key's health for monitoring / dashboards.

        Returned shape per key:

            {key_tail, calls, errors_429, cooling_for_sec,
             consecutive_429s, last_success_at, last_429_at}

        Only the last 6 chars of each key are exposed — enough to map
        back to the operator's `.env` order without leaking secrets in
        logs or in the /api/v1/llm/pool-stats response.
        """
        with self._lock:
            now = time.time()
            return [
                {
                    "key_tail": state.api_key[-6:],
                    "calls": state.total_calls,
                    "errors_429": state.total_429s,
                    "cooling_for_sec": round(
                        max(0.0, state.cooldown_until - now), 1,
                    ),
                    "consecutive_429s": state.consecutive_429s,
                    "last_success_at": (
                        state.last_success_at if state.last_success_at else None
                    ),
                    "last_429_at": (
                        state.last_429_at if state.last_429_at else None
                    ),
                }
                for state in self._states
            ]

    def __len__(self) -> int:
        return len(self._states)


# ── module-level singleton so callers don't pay setup cost per call ──

_GLOBAL_POOL: GroqKeyPool | None = None
_GLOBAL_POOL_LOCK = threading.Lock()


def get_groq_pool() -> GroqKeyPool | None:
    """Return the process-wide pool. Initialised on first call from the
    ``GROQ_API_KEYS`` env var (comma-separated). Falls back to a
    single-key pool from ``GROQ_API_KEY`` for back-compat.

    Returns ``None`` only when neither env var is set — callers should
    treat that as "LLM disabled" and abort gracefully.
    """
    global _GLOBAL_POOL
    if _GLOBAL_POOL is not None:
        return _GLOBAL_POOL
    with _GLOBAL_POOL_LOCK:
        if _GLOBAL_POOL is not None:
            return _GLOBAL_POOL
        import os
        pooled = os.environ.get("GROQ_API_KEYS", "").strip()
        single = os.environ.get("GROQ_API_KEY", "").strip()
        keys: list[str] = []
        if pooled:
            keys = [k.strip() for k in pooled.split(",") if k.strip()]
        elif single:
            keys = [single]
        if not keys:
            return None
        _GLOBAL_POOL = GroqKeyPool(keys)
        log.info("GroqKeyPool initialised with %d key(s)", len(_GLOBAL_POOL))
        return _GLOBAL_POOL


def _reset_pool_for_tests() -> None:
    """Test hook — never call in production."""
    global _GLOBAL_POOL
    with _GLOBAL_POOL_LOCK:
        _GLOBAL_POOL = None
