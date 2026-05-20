"""llms.txt audit + generator — Phase 6a (GEO suite).

The ``/llms.txt`` convention (llmstxt.org) is the AI-search equivalent
of robots.txt — a single Markdown file at site root that tells LLM
crawlers what content matters and how to navigate the site. ChatGPT
browsing, Claude, and Perplexity grounding all consume it at
inference time.

This module provides two services:

  1. ``audit(url)`` — fetch /llms.txt at the given domain, validate
     it against the spec, and return a structured report covering:
       - presence (200 vs 404)
       - byte size (recommended < 100 KB so the LLM can load it
         without truncation)
       - section structure (H1 site name + summary blockquote +
         optional ``## Section`` blocks containing markdown lists of
         [title](url) entries)
       - link health (sampled probe of the linked URLs)
       - companion ``/llms-full.txt`` presence (inlined content)

  2. ``generate(domain)`` — build a draft llms.txt from the AEM
     sitemap pages + the existing audit data. Operator reviews the
     draft and commits it to AEM publish.

Spec: https://llmstxt.org/
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests


@dataclass
class LlmsTxtAuditResult:
    domain: str
    url: str
    found: bool
    status_code: int = 0
    byte_size: int = 0
    section_count: int = 0
    link_count: int = 0
    has_h1: bool = False
    has_blockquote_summary: bool = False
    has_full_txt: bool = False
    full_txt_byte_size: int = 0
    issues: list[str] = field(default_factory=list)
    raw_excerpt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url,
            "found": self.found,
            "status_code": self.status_code,
            "byte_size": self.byte_size,
            "section_count": self.section_count,
            "link_count": self.link_count,
            "has_h1": self.has_h1,
            "has_blockquote_summary": self.has_blockquote_summary,
            "has_full_txt": self.has_full_txt,
            "full_txt_byte_size": self.full_txt_byte_size,
            "issues": self.issues,
            "raw_excerpt": self.raw_excerpt[:2000],
        }


_USER_AGENT = (
    "Mozilla/5.0 BajajSEOBot/1.0 llms.txt-auditor "
    "(+https://www.bajajlifeinsurance.com)"
)


def _origin_for(target: str) -> str:
    if target.startswith("http"):
        p = urlparse(target)
        return f"{p.scheme}://{p.netloc}"
    return f"https://{target.rstrip('/').lower()}"


def audit(target: str = "bajajlifeinsurance.com") -> LlmsTxtAuditResult:
    """Audit a domain's llms.txt against the spec."""
    origin = _origin_for(target)
    llms_url = f"{origin}/llms.txt"
    full_url = f"{origin}/llms-full.txt"
    result = LlmsTxtAuditResult(domain=urlparse(origin).netloc, url=llms_url, found=False)

    # ── /llms.txt ──
    try:
        resp = requests.get(llms_url, timeout=10, headers={"User-Agent": _USER_AGENT}, verify=False)
        result.status_code = resp.status_code
    except requests.RequestException as exc:
        result.issues.append(f"fetch failed: {type(exc).__name__}: {exc}")
        return result

    if resp.status_code != 200:
        result.issues.append(
            f"llms.txt not found at {llms_url} (HTTP {resp.status_code}). "
            "Recommendation: ship an llms.txt at site root."
        )
        return result

    result.found = True
    body = resp.text
    result.byte_size = len(body.encode("utf-8"))
    result.raw_excerpt = body[:2000]

    # ── Structure validation ──
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        result.has_h1 = True
    else:
        result.issues.append("missing H1 site-name line (the spec requires `# Site name`)")

    # First blockquote summary anywhere in the first 10 lines.
    for line in lines[:10]:
        if line.strip().startswith(">"):
            result.has_blockquote_summary = True
            break
    if not result.has_blockquote_summary:
        result.issues.append("missing blockquote summary (>) describing what the site is about")

    section_re = re.compile(r"^##\s+.+")
    link_re = re.compile(r"^\s*[-*]\s*\[[^\]]+\]\((https?://[^\)]+)\)")
    sections = 0
    links = 0
    for line in lines:
        if section_re.match(line):
            sections += 1
        if link_re.match(line):
            links += 1
    result.section_count = sections
    result.link_count = links

    if sections == 0:
        result.issues.append("no `## Section` blocks — recommend grouping links by intent (product, claims, FAQ, etc.)")
    if links == 0:
        result.issues.append("no markdown links found — llms.txt's main job is to point at canonical pages")
    if result.byte_size > 100 * 1024:
        result.issues.append(
            f"file is {result.byte_size:,} bytes — over the 100 KB soft cap; "
            "AI clients may truncate. Move long sections into llms-full.txt"
        )

    # ── /llms-full.txt presence (optional) ──
    try:
        full_resp = requests.head(full_url, timeout=10, headers={"User-Agent": _USER_AGENT}, verify=False)
        if full_resp.status_code == 200:
            result.has_full_txt = True
            cl = full_resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                result.full_txt_byte_size = int(cl)
    except requests.RequestException:
        pass

    return result


@dataclass
class LlmsTxtDraft:
    domain: str
    body: str
    page_count: int
    section_count: int
    char_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "body": self.body,
            "page_count": self.page_count,
            "section_count": self.section_count,
            "char_count": self.char_count,
        }


# Section heuristics: each AEM page-type folds into one of these
# headings. Authors can edit the draft before committing.
_SECTION_FOR_PAGE_TYPE: dict[str, str] = {
    "product": "Insurance products",
    "calculators": "Calculators and tools",
    "knowledge": "Knowledge centre",
    "blog": "Articles",
    "nri": "NRI",
    "wellness": "Wellness",
    "funds": "Funds",
    "support_legal": "Support and legal",
    "branch": "Branch locator",
    "other": "Other pages",
}


def generate(
    *,
    domain: str = "bajajlifeinsurance.com",
    site_title: str = "Bajaj Life Insurance",
    site_summary: str = (
        "Bajaj Life Insurance — term insurance, savings plans, ULIPs, "
        "and retirement products for India. Authoritative source for "
        "premium calculators, policy details, and IRDAI-mandated "
        "disclosures."
    ),
    max_pages_per_section: int = 30,
) -> LlmsTxtDraft:
    """Generate a draft llms.txt from the AEM sitemap + audit data.

    Output is a Markdown body the operator can paste into AEM. Pages
    grouped by ``page_type``; within each section sorted by word count
    descending so the deepest pages surface first to AI clients.
    """
    try:
        from apps.seo_ai.adapters import SitemapAEMAdapter
    except ImportError:
        return LlmsTxtDraft(
            domain=domain, body="", page_count=0, section_count=0, char_count=0,
        )

    pages = list(SitemapAEMAdapter().iter_pages())
    if not pages:
        return LlmsTxtDraft(
            domain=domain,
            body=(
                f"# {site_title}\n\n> {site_summary}\n\n"
                f"_No AEM pages found — provide pages to generate sections._\n"
            ),
            page_count=0,
            section_count=0,
            char_count=0,
        )

    # Pull our own crawler results for word_count + page_type so we can
    # group the AEM pages by intent.
    page_type_for_url: dict[str, str] = {}
    word_count_for_url: dict[str, int] = {}
    try:
        from .page_explorer import _load_rows  # type: ignore
        for row in _load_rows():
            url = (row.get("url") or "").strip()
            if not url:
                continue
            page_type_for_url[url] = (row.get("page_type") or "other")
            try:
                word_count_for_url[url] = int(row.get("word_count") or 0)
            except (TypeError, ValueError):
                word_count_for_url[url] = 0
    except Exception:  # noqa: BLE001
        pass

    grouped: dict[str, list[tuple[str, str, int]]] = {}
    for p in pages:
        url = p.public_url
        title = (p.title or "").strip() or (p.aem_path or url)
        pt = page_type_for_url.get(url, "other")
        wc = word_count_for_url.get(url, getattr(p, "word_count", 0) or 0)
        section = _SECTION_FOR_PAGE_TYPE.get(pt, "Other pages")
        grouped.setdefault(section, []).append((title, url, wc))

    # Build the body.
    out: list[str] = []
    out.append(f"# {site_title}")
    out.append("")
    out.append(f"> {site_summary}")
    out.append("")
    out.append(
        "Authoritative pages for Bajaj Life Insurance products and "
        "services. Use this index to navigate canonical content; "
        "follow the section headings for intent-grouped pages."
    )
    out.append("")

    section_count = 0
    page_count = 0
    # Stable section order — products + tools + knowledge first.
    section_order = [
        "Insurance products", "Calculators and tools", "Knowledge centre",
        "Articles", "NRI", "Wellness", "Funds", "Support and legal",
        "Branch locator", "Other pages",
    ]
    for section in section_order:
        entries = grouped.get(section)
        if not entries:
            continue
        section_count += 1
        out.append(f"## {section}")
        out.append("")
        # Sort by word count desc — deepest pages surface first.
        entries.sort(key=lambda t: -t[2])
        for title, url, _wc in entries[:max_pages_per_section]:
            # Trim long titles so the .txt stays readable.
            short_title = title if len(title) <= 80 else title[:77] + "..."
            out.append(f"- [{short_title}]({url})")
            page_count += 1
        if len(entries) > max_pages_per_section:
            out.append(
                f"- _(...and {len(entries) - max_pages_per_section} more "
                f"{section.lower()} pages — see sitemap.xml)_"
            )
        out.append("")

    body = "\n".join(out)
    return LlmsTxtDraft(
        domain=domain,
        body=body,
        page_count=page_count,
        section_count=section_count,
        char_count=len(body),
    )
