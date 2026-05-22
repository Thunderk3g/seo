"""RSS feed adapter — Indian business publications.

Polls a curated list of Indian-finance RSS feeds (Economic Times,
Livemint, Moneycontrol, Business Standard, Financial Express, ETBFSI)
and filters items where the title or description contains any
configured brand variant. No API key, no quota — just HTTP GETs to
public RSS endpoints.

Why this is the highest-yield source for Bajaj:
  * Indian financial news is where the rebrand stickiness shows
    (analysts still write "Bajaj Allianz Life" because that's what
    they've cited for years)
  * News sites are tier-1 authority signals — Google + AI bots weight
    these heavily when deciding what to say about Bajaj
  * Real-time (sub-hour lag) and 100% free

Failure handling: any feed that fails to parse is logged once and
skipped. One bad feed doesn't kill the run. The adapter is fully
idempotent — re-running an hour later only writes net-new items.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import requests
from django.conf import settings

from .classify import (
    classify_brand_variant,
    classify_source_tier,
    domain_of,
    extract_snippet,
)

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

log = logging.getLogger("apps.seo_ai.adapters.brand_mentions.rss_news")


@dataclass
class FeedItem:
    """One RSS entry that matched a brand variant. Normalised so the
    orchestrator can hand it to the persistence layer without knowing
    which feed it came from."""

    source_url: str
    source_domain: str
    source_title: str
    snippet: str
    brand_variant: str
    source_tier: str
    published_at: datetime | None = None
    raw_payload: dict = field(default_factory=dict)


# ── feedparser-free RSS parsing ──────────────────────────────────────


def _parse_rss(xml_text: str) -> list[dict]:
    """Minimal RSS / Atom parser.

    We avoid the ``feedparser`` dependency because the existing
    project doesn't ship it and the schemas we care about (RSS 2.0
    + Atom 1.0) are simple enough to handle with the standard-lib
    XML parser. If a feed uses an exotic format the per-item loop
    just skips silently and we log once at INFO level.
    """
    from xml.etree import ElementTree as ET

    # Strip BOM / leading whitespace that some publications include.
    body = xml_text.lstrip("﻿\r\n\t ")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        log.info("rss: parse error: %s", exc)
        return []

    items: list[dict] = []
    # RSS 2.0: <rss><channel><item>...
    for ch in root.iter():
        # Strip namespace from tag for portable comparisons.
        tag = ch.tag.split("}", 1)[-1].lower()
        if tag != "item":
            continue
        item: dict[str, str] = {}
        for child in ch:
            ctag = child.tag.split("}", 1)[-1].lower()
            text = (child.text or "").strip()
            if not text and child.get("href"):
                text = child.get("href", "").strip()
            if ctag in ("title", "link", "description", "summary",
                        "pubdate", "published", "updated"):
                item[ctag] = text
        if item.get("link") or item.get("title"):
            items.append(item)
    # Atom 1.0 fallback: <feed><entry>...
    if not items:
        for ch in root.iter():
            tag = ch.tag.split("}", 1)[-1].lower()
            if tag != "entry":
                continue
            item: dict[str, str] = {}
            for child in ch:
                ctag = child.tag.split("}", 1)[-1].lower()
                if ctag == "link":
                    item["link"] = child.get("href", "") or (child.text or "").strip()
                elif ctag in ("title", "summary", "content", "updated", "published"):
                    item[ctag] = (child.text or "").strip()
            if item.get("link") or item.get("title"):
                items.append(item)
    return items


_RFC_822_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S GMT",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_published(raw: str) -> datetime | None:
    """Try the common date formats RSS/Atom publishers use. Returns
    None when nothing parses — caller falls back to ``last_seen_at``."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in _RFC_822_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ── adapter ──────────────────────────────────────────────────────────


def fetch_rss_mentions(
    *, brand_pattern: re.Pattern[str] | None = None,
    timeout: int = 20,
) -> list[FeedItem]:
    """Poll every configured RSS feed and return matched items.

    Pattern is built once from the configured brand tokens so we don't
    re-compile per feed. The match is case-insensitive over title +
    description combined.

    Net-new vs already-stored filtering happens in the orchestrator
    (it uses ``update_or_create`` on ``source_url``) — this adapter
    just emits every match it finds.
    """
    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    feeds: list[str] = cfg.get("rss_feeds") or []
    if not feeds:
        log.info("rss: no feeds configured")
        return []

    if brand_pattern is None:
        from .classify import all_brand_tokens
        brand_pattern = re.compile(
            "|".join(re.escape(t) for t in all_brand_tokens()),
            re.IGNORECASE,
        )

    verify = _resolve_ssl_verify(cfg.get("ssl_verify", "false"))
    if verify is False:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass

    out: list[FeedItem] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (BajajSEOMonitor/1.0; +https://www.bajajlifeinsurance.com)"
        ),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    for feed_url in feeds:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=timeout, verify=verify)
        except requests.RequestException as exc:
            log.info("rss %s: fetch failed: %s", feed_url, exc)
            continue
        if resp.status_code != 200 or not resp.text:
            log.info("rss %s: HTTP %s, body=%d", feed_url, resp.status_code, len(resp.text or ""))
            continue
        items = _parse_rss(resp.text)
        feed_host = domain_of(feed_url)
        log.info("rss %s: %d items parsed (host=%s)", feed_url, len(items), feed_host)
        for it in items:
            title = it.get("title") or ""
            link = it.get("link") or ""
            desc = it.get("description") or it.get("summary") or it.get("content") or ""
            haystack = f"{title} {desc}"
            if not brand_pattern.search(haystack):
                continue
            if not link or not link.startswith(("http://", "https://")):
                continue

            variant = classify_brand_variant(title, desc)
            tier = classify_source_tier(link or feed_url)
            published = _parse_published(
                it.get("pubdate") or it.get("published") or it.get("updated") or ""
            )
            snippet = extract_snippet(desc, around_match="Bajaj", length=240)
            out.append(FeedItem(
                source_url=link[:2000],
                source_domain=(domain_of(link) or feed_host)[:255],
                source_title=title[:512],
                snippet=snippet,
                brand_variant=variant,
                source_tier=tier,
                published_at=published,
                raw_payload={
                    "feed_url": feed_url,
                    "raw_title": title,
                    "raw_desc": desc[:2000],
                },
            ))
    log.info("rss: emitted %d matched items across %d feeds", len(out), len(feeds))
    return out


def _resolve_ssl_verify(raw: str) -> bool | str:
    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    import os
    if os.path.exists(value):
        return value
    return True
