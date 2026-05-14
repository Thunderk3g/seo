"""AEM page-model JSON adapter.

The ``sitemap/`` directory contains JSON exports from Adobe Experience
Manager. Each file is an array of page-model objects, where every
element is a single page with a ``path`` (under
``/content/balic-web/en/...``) and a deep component tree under
``model.:items.root``.

Why we read this instead of crawling: AEM is the **authoring** source
of truth — it knows declared titles, descriptions, last-modified
dates, and the component composition of each page. The live HTML can
deviate (cached templates, deployment lag), so the Content Analyzer
prefers the AEM record for "what was authored" and reconciles against
the crawler record for "what is shipped".

Path → public URL mapping: strip ``/content/balic-web/en`` prefix and
prepend ``https://www.bajajlifeinsurance.com``. Anything that does not
match the prefix is skipped — AEM occasionally exports admin paths
that aren't part of the public site.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from django.conf import settings

logger = logging.getLogger("seo.ai.adapters.aem")

_PATH_PREFIX = "/content/balic-web/en"
_PUBLIC_BASE = "https://www.bajajlifeinsurance.com"


@dataclass
class AEMPage:
    public_url: str
    aem_path: str
    title: str
    description: str
    template_name: str
    last_modified: datetime | None
    component_count: int
    component_types: list[str]
    # Concatenated body content from every text-bearing component in the
    # page-model tree. Empty when the export has no text components
    # (rare — usually means a redirect or admin stub).
    content: str = ""
    word_count: int = 0


@dataclass
class AEMSummary:
    total_pages: int
    pages_with_description: int
    pages_with_short_title: int   # < 30 chars
    pages_with_long_title: int    # > 60 chars
    pages_with_short_desc: int    # < 70 chars
    pages_with_long_desc: int     # > 160 chars
    pages_without_description: int
    distinct_templates: list[str]
    component_usage: dict[str, int]  # "Accordion Cards" -> 412
    most_recent_modification: datetime | None
    least_recent_modification: datetime | None
    snapshot_path: str


class SitemapAEMAdapter:
    """Read-only access to the AEM JSON exports."""

    def __init__(self, sitemap_dir: Path | str | None = None) -> None:
        self.sitemap_dir = (
            Path(sitemap_dir) if sitemap_dir else settings.SEO_AI["sitemap_dir"]
        )

    # ── iteration ─────────────────────────────────────────────────────

    def files(self) -> list[Path]:
        if not self.sitemap_dir.exists():
            return []
        # AEM exports may be duplicated as "name (1).json" / "name (2).json"
        # in user downloads. We dedupe by file content hash later, but
        # here we just return everything; the iterator caller can dedupe
        # on ``aem_path``.
        return sorted(p for p in self.sitemap_dir.glob("*.json") if p.is_file())

    def iter_pages(self) -> Iterable[AEMPage]:
        seen: set[str] = set()
        for path in self.files():
            try:
                with path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("sitemap unreadable: %s (%s)", path, exc)
                continue
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                page = _to_page(entry)
                if page is None or page.aem_path in seen:
                    continue
                seen.add(page.aem_path)
                yield page

    # ── rollups ───────────────────────────────────────────────────────

    def summary(self) -> AEMSummary:
        total = 0
        with_desc = 0
        short_title = 0
        long_title = 0
        short_desc = 0
        long_desc = 0
        missing_desc = 0
        templates: set[str] = set()
        component_usage: dict[str, int] = {}
        most_recent: datetime | None = None
        least_recent: datetime | None = None

        for page in self.iter_pages():
            total += 1
            if page.description:
                with_desc += 1
                if len(page.description) < 70:
                    short_desc += 1
                elif len(page.description) > 160:
                    long_desc += 1
            else:
                missing_desc += 1
            tl = len(page.title or "")
            if tl > 0 and tl < 30:
                short_title += 1
            elif tl > 60:
                long_title += 1
            if page.template_name:
                templates.add(page.template_name)
            for ctype in page.component_types:
                component_usage[ctype] = component_usage.get(ctype, 0) + 1
            if page.last_modified:
                if most_recent is None or page.last_modified > most_recent:
                    most_recent = page.last_modified
                if least_recent is None or page.last_modified < least_recent:
                    least_recent = page.last_modified

        return AEMSummary(
            total_pages=total,
            pages_with_description=with_desc,
            pages_with_short_title=short_title,
            pages_with_long_title=long_title,
            pages_with_short_desc=short_desc,
            pages_with_long_desc=long_desc,
            pages_without_description=missing_desc,
            distinct_templates=sorted(templates),
            component_usage=dict(
                sorted(component_usage.items(), key=lambda kv: kv[1], reverse=True)[:30]
            ),
            most_recent_modification=most_recent,
            least_recent_modification=least_recent,
            snapshot_path=str(self.sitemap_dir),
        )


# ── helpers ──────────────────────────────────────────────────────────────


def _to_page(entry: dict) -> AEMPage | None:
    aem_path = entry.get("path") or ""
    if not aem_path.startswith(_PATH_PREFIX):
        return None
    model = entry.get("model") or {}
    public = _PUBLIC_BASE + aem_path[len(_PATH_PREFIX) :] + ".html"
    last_mod_raw = model.get("lastModifiedDate")
    last_mod: datetime | None = None
    if isinstance(last_mod_raw, (int, float)):
        # AEM emits epoch milliseconds.
        try:
            last_mod = datetime.fromtimestamp(last_mod_raw / 1000, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            last_mod = None
    elif isinstance(last_mod_raw, str):
        try:
            last_mod = datetime.fromisoformat(last_mod_raw.replace("Z", "+00:00"))
        except ValueError:
            last_mod = None

    components: list[str] = []
    items = (model.get(":items") or {}).get("root") or {}
    allowed = items.get("allowedComponents") or {}
    for comp in allowed.get("components") or []:
        title = comp.get("title")
        if isinstance(title, str) and title.strip():
            components.append(title.strip())

    content_blocks = _extract_content(model)
    content_str = "\n\n".join(content_blocks)
    word_count = sum(1 for w in content_str.split() if w)

    return AEMPage(
        public_url=public,
        aem_path=aem_path,
        title=(model.get("title") or "").strip(),
        description=(model.get("description") or "").strip(),
        template_name=(model.get("templateName") or "").strip(),
        last_modified=last_mod,
        component_count=len(components),
        component_types=components,
        content=content_str,
        word_count=word_count,
    )


# Fields on AEM component nodes that carry user-visible body content.
# Order matters only for stability across runs — the extraction itself
# deduplicates so repeated nav/footer fragments don't blow up the
# payload.
_CONTENT_FIELDS = ("text", "content", "heading", "subtitle", "body", "plaintext")


def _extract_content(node, out=None, seen=None):
    """Recursively walk a page-model node and collect text content.

    Returns a list of text blocks in document order with duplicates
    suppressed. ``content`` and ``text`` can be HTML — we strip tags so
    the frontend doesn't need to render unsafe markup.
    """
    if out is None:
        out = []
    if seen is None:
        seen = set()
    if isinstance(node, dict):
        for key in _CONTENT_FIELDS:
            val = node.get(key)
            if isinstance(val, str):
                cleaned = _strip_html(val).strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    out.append(cleaned)
        for v in node.values():
            if isinstance(v, (dict, list)):
                _extract_content(v, out, seen)
    elif isinstance(node, list):
        for v in node:
            _extract_content(v, out, seen)
    return out


def _strip_html(raw: str) -> str:
    """Cheap HTML → text. AEM emits simple tags (``<p><b><sup>...``) —
    no need to pull in BeautifulSoup for this.
    """
    import re

    # Replace block-level tags with newlines so paragraphs stay readable.
    text = re.sub(r"</(p|div|li|h[1-6]|br|tr)\s*>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Common HTML entities — AEM mostly emits &amp; / &nbsp; / &#xNN;.
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return text
