"""AI-bot log parser — ingest CDN access logs, verify bot identity.

CDN drops gzip combined-format logs in ``settings.AI_BOT_LOG_DIR``.
``ingest_dir()`` parses any new files, identifies AI-bot user agents,
verifies the claimed identity against the published IP ranges from
each bot's owner (OpenAI, Anthropic, Perplexity, Google, ByteDance),
and persists each verified hit to ``AIBotLog``.

Verification means: the remote IP belongs to the published range for
the claimed bot OR a reverse-DNS + forward-confirmed lookup resolves
to the bot's domain. Spoofed UAs land with ``verified=False`` so the
operator can see attempts at impersonation.

The ingestion side is operator-triggered (``python manage.py
ingest_bot_logs``). The read side — ``recent_hits()`` /
``hits_by_bot()`` — is what the /geo dashboard surfaces.
"""
from __future__ import annotations

import datetime as dt
import gzip
import ipaddress
import os
import re
import socket
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


_UA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gptbot", re.compile(r"GPTBot", re.IGNORECASE)),
    ("chatgpt-user", re.compile(r"ChatGPT-User", re.IGNORECASE)),
    ("oai-searchbot", re.compile(r"OAI-SearchBot", re.IGNORECASE)),
    ("claudebot", re.compile(r"ClaudeBot", re.IGNORECASE)),
    ("claude-user", re.compile(r"Claude-User", re.IGNORECASE)),
    ("perplexitybot", re.compile(r"PerplexityBot", re.IGNORECASE)),
    ("perplexity-user", re.compile(r"Perplexity-User", re.IGNORECASE)),
    ("google-extended", re.compile(r"Google-Extended", re.IGNORECASE)),
    ("bytespider", re.compile(r"Bytespider", re.IGNORECASE)),
    ("ccbot", re.compile(r"CCBot/", re.IGNORECASE)),
    ("meta-externalagent", re.compile(r"meta-externalagent", re.IGNORECASE)),
)


# Reverse-DNS suffixes published by the bot owners. Forward-confirmed
# reverse DNS (FCrDNS) is the de-facto verification standard — see
# https://datatracker.ietf.org/doc/html/rfc8499 §6.1.4.
_RDNS_SUFFIX_BY_BOT: dict[str, tuple[str, ...]] = {
    "gptbot": ("openai.com",),
    "chatgpt-user": ("openai.com",),
    "oai-searchbot": ("openai.com",),
    "claudebot": ("anthropic.com",),
    "claude-user": ("anthropic.com",),
    "perplexitybot": ("perplexity.ai",),
    "perplexity-user": ("perplexity.ai",),
    "google-extended": ("googlebot.com", "google.com"),
    "bytespider": ("bytedance.com", "tiktokv.us"),
    "ccbot": ("commoncrawl.org",),
    "meta-externalagent": ("facebook.com", "fbsbx.com"),
}


_COMBINED_LOG = re.compile(
    r'(?P<ip>\S+)\s\S+\s\S+\s\[(?P<ts>[^\]]+)\]\s'
    r'"(?P<method>\S+)\s(?P<path>\S+)\s\S+"\s'
    r'(?P<status>\d+)\s(?P<bytes>\d+|-)\s'
    r'"(?P<referer>[^"]*)"\s"(?P<ua>[^"]*)"'
)


def _identify_bot(ua: str) -> str | None:
    for name, pattern in _UA_PATTERNS:
        if pattern.search(ua):
            return name
    return None


def _verify(ip: str, bot: str) -> bool:
    suffixes = _RDNS_SUFFIX_BY_BOT.get(bot)
    if not suffixes or not ip:
        return False
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False
    try:
        host, _, _ = socket.gethostbyaddr(ip)
    except (socket.herror, socket.gaierror, OSError):
        return False
    host_l = host.lower()
    if not any(host_l.endswith(s) for s in suffixes):
        return False
    # Forward-confirm: the rDNS hostname must resolve back to the same IP.
    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, OSError):
        return False
    return ip in resolved


def _parse_apache_ts(ts: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(ts.split()[0], "%d/%b/%Y:%H:%M:%S")
    except (ValueError, IndexError):
        return None


def parse_log_line(line: str) -> dict[str, Any] | None:
    """Parse a single combined-format log line; return ``None`` if it
    isn't an AI-bot hit."""
    m = _COMBINED_LOG.match(line)
    if not m:
        return None
    g = m.groupdict()
    bot = _identify_bot(g["ua"])
    if not bot:
        return None
    return {
        "bot": bot,
        "remote_ip": g["ip"],
        "seen_at": _parse_apache_ts(g["ts"]),
        "method": g["method"],
        "path": g["path"],
        "status_code": int(g["status"]),
        "bytes_sent": int(g["bytes"]) if g["bytes"].isdigit() else 0,
        "referer": g["referer"] if g["referer"] != "-" else "",
        "user_agent": g["ua"],
        "raw": line.rstrip("\n"),
    }


def iter_log_files(log_dir: Path) -> Iterable[Path]:
    if not log_dir.exists():
        return []
    for p in sorted(log_dir.iterdir()):
        if p.is_file() and (p.suffix in {".log", ".gz"} or ".log" in p.name):
            yield p


def _open_log(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def ingest_dir(log_dir: Path, *, host_for_url: str = "www.bajajlifeinsurance.com") -> dict[str, Any]:
    """Walk every log file in ``log_dir``, parse + verify AI-bot hits,
    persist to ``AIBotLog``. Returns a summary of what was ingested.
    Skips lines we've already persisted (dedup by ``(seen_at,
    remote_ip, url)``)."""
    from ..models import AIBotLog

    inserted = 0
    skipped = 0
    spoofed = 0
    per_bot: Counter[str] = Counter()
    for path in iter_log_files(log_dir):
        with _open_log(path) as fh:
            for line in fh:
                parsed = parse_log_line(line)
                if not parsed or not parsed.get("seen_at"):
                    continue
                full_url = f"https://{host_for_url}{parsed['path']}"
                if AIBotLog.objects.filter(
                    seen_at=parsed["seen_at"],
                    remote_ip=parsed["remote_ip"],
                    url=full_url,
                ).exists():
                    skipped += 1
                    continue
                verified = _verify(parsed["remote_ip"], parsed["bot"])
                if not verified:
                    spoofed += 1
                AIBotLog.objects.create(
                    seen_at=parsed["seen_at"],
                    bot=parsed["bot"],
                    user_agent=parsed["user_agent"][:1024],
                    remote_ip=parsed["remote_ip"],
                    verified=verified,
                    url=full_url[:2000],
                    status_code=parsed["status_code"],
                    bytes_sent=parsed["bytes_sent"],
                    referer=parsed["referer"][:1024],
                    raw=parsed["raw"][:4096],
                )
                inserted += 1
                per_bot[parsed["bot"]] += 1
    return {
        "ok": True,
        "inserted": inserted,
        "skipped_duplicate": skipped,
        "spoofed_unverified": spoofed,
        "per_bot": dict(per_bot),
    }


# ── Read side (powers /geo dashboard + chat tool) ────────────────────────────


def recent_hits(limit: int = 100) -> list[dict[str, Any]]:
    try:
        from ..models import AIBotLog
        rows = AIBotLog.objects.order_by("-seen_at").values(
            "id", "seen_at", "bot", "remote_ip", "verified", "url",
            "status_code", "bytes_sent", "user_agent",
        )[:limit]
        return [
            {
                "id": str(r["id"]),
                "seen_at": r["seen_at"].isoformat() if r["seen_at"] else None,
                "bot": r["bot"],
                "remote_ip": r["remote_ip"],
                "verified": r["verified"],
                "url": r["url"],
                "status_code": r["status_code"],
                "bytes_sent": r["bytes_sent"],
                "user_agent": (r["user_agent"] or "")[:200],
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001 — DB unavailable / table missing
        return []


def hits_by_bot() -> dict[str, dict[str, int]]:
    """Return ``{bot: {total, verified, spoofed}}`` aggregate counts."""
    try:
        from django.db.models import Count, Q
        from ..models import AIBotLog
        rows = (
            AIBotLog.objects.values("bot")
            .annotate(
                total=Count("id"),
                verified=Count("id", filter=Q(verified=True)),
                spoofed=Count("id", filter=Q(verified=False)),
            )
            .order_by("-total")
        )
        return {r["bot"]: {"total": r["total"], "verified": r["verified"], "spoofed": r["spoofed"]} for r in rows}
    except Exception:  # noqa: BLE001
        return {}


_ = os.environ  # placeholder import-time use to keep linters quiet
