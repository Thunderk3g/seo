"""Phase C — SF parity helpers for JS render-delta, PDF metadata,
custom XPath/CSS extractors, and spelling/readability.

Each function is pure / no I/O beyond what the caller already has
(the response body, or the PDF bytes already streamed). Detectors in
``detectors_phase_c.py`` read the stamped fields back out.

  * render_delta_from(static_word_count, rendered_word_count,
                      static_link_count, rendered_link_count,
                      static_jsonld_count, rendered_jsonld_count)
        → content_delta_ratio + js_dependent_* flags

  * pdf_metadata_from(body_bytes)
        → title, author, page_count, language, has_text_layer,
          is_encrypted, byte_size

  * custom_extractors_run(html, extractors)
        → dict mapping extractor name → first matched value
          (XPath or CSS selector, decided per extractor)

  * readability_signals_from(text)
        → flesch_score, grade_level, word_count, sentence_count,
          spelling_error_count, spelling_errors (capped sample)

Heavy deps (pypdf, lxml, textstat, pyspellchecker) are imported
lazily inside the functions — operators that disable a feature
shouldn't have to install the corresponding package.
"""
from __future__ import annotations

import io
import re
from typing import Any


# ── C.1 — JS render-delta ─────────────────────────────────────────


def render_delta_from(
    static_word_count: int | None,
    rendered_word_count: int | None,
    static_link_count: int | None = None,
    rendered_link_count: int | None = None,
    static_jsonld_count: int | None = None,
    rendered_jsonld_count: int | None = None,
) -> dict:
    """Return the delta signals consumed by the JS-dependent
    detectors. Returns a flat dict keyed by model-field name.

    When the page never went through Playwright (most pages), the
    ``rendered_*`` arguments are None and we return zeros — the
    detectors will not fire on these rows.
    """
    if rendered_word_count is None or static_word_count is None:
        return {
            "content_delta_ratio": 0.0,
            "link_delta_ratio": 0.0,
            "jsonld_delta_ratio": 0.0,
            "js_rendered": False,
        }
    sw = max(0, int(static_word_count))
    rw = max(0, int(rendered_word_count))
    # Ratio of NEW content that only appears after JS execution.
    # 0.0 means static == rendered; 1.0 means everything was JS-added.
    content_delta = (rw - sw) / rw if rw > 0 else 0.0
    content_delta = max(0.0, min(1.0, content_delta))

    def _delta(s, r):
        s = max(0, int(s or 0))
        r = max(0, int(r or 0))
        return max(0.0, min(1.0, (r - s) / r if r > 0 else 0.0))

    return {
        "content_delta_ratio": round(content_delta, 4),
        "link_delta_ratio": round(_delta(static_link_count, rendered_link_count), 4),
        "jsonld_delta_ratio": round(_delta(static_jsonld_count, rendered_jsonld_count), 4),
        "js_rendered": True,
    }


# ── C.2 — PDF metadata ─────────────────────────────────────────────


def pdf_metadata_from(body_bytes: bytes) -> dict:
    """Extract PDF metadata using pypdf (lazy import).

    Returns title, author, subject, page_count, language,
    has_text_layer, is_encrypted, byte_size. Best-effort — any
    parse error returns a row of empties so the caller never has to
    handle exceptions.
    """
    empty = {
        "pdf_title": "", "pdf_author": "", "pdf_subject": "",
        "pdf_page_count": 0, "pdf_language": "",
        "pdf_has_text_layer": False, "pdf_is_encrypted": False,
        "pdf_byte_size": len(body_bytes or b""),
    }
    if not body_bytes:
        return empty
    try:
        from pypdf import PdfReader  # lazy import
    except ImportError:
        return empty
    try:
        reader = PdfReader(io.BytesIO(body_bytes))
    except Exception:  # noqa: BLE001 — malformed PDF
        return empty

    out = dict(empty)
    out["pdf_is_encrypted"] = bool(getattr(reader, "is_encrypted", False))
    try:
        meta = reader.metadata or {}
        out["pdf_title"] = (meta.get("/Title") or "")[:512]
        out["pdf_author"] = (meta.get("/Author") or "")[:256]
        out["pdf_subject"] = (meta.get("/Subject") or "")[:512]
        out["pdf_language"] = (meta.get("/Language") or "")[:32]
    except Exception:  # noqa: BLE001
        pass

    try:
        pages = reader.pages
        out["pdf_page_count"] = len(pages)
        # Sample first 3 pages for text layer; scanned PDFs return ""
        sample_text = ""
        for page in list(pages)[:3]:
            try:
                sample_text += page.extract_text() or ""
            except Exception:  # noqa: BLE001
                continue
        out["pdf_has_text_layer"] = len(sample_text.strip()) > 50
    except Exception:  # noqa: BLE001
        pass

    return out


# ── C.3 — Custom XPath / CSS extractors ────────────────────────────


def custom_extractors_run(html: str, extractors: list[dict]) -> dict:
    """Apply each user-defined extractor to the page; return a dict
    mapping extractor name to first matched value (string).

    ``extractors`` shape:
        [
          {"name": "price",       "type": "css",   "selector": ".price-tag"},
          {"name": "h1_first",    "type": "xpath", "selector": "//h1[1]"},
          {"name": "review_n",    "type": "css",   "selector": "[itemprop=ratingCount]"},
        ]

    Each extractor returns ONE value (first match) — the SF-style
    "extract first matching node's text". Multi-match support would
    explode the storage shape; this matches SF's defaults.
    """
    out: dict[str, str] = {}
    if not html or not extractors:
        return out

    css_extractors = [e for e in extractors if (e.get("type") or "css") == "css"]
    xpath_extractors = [e for e in extractors if (e.get("type") or "").lower() == "xpath"]

    if css_extractors:
        try:
            from bs4 import BeautifulSoup  # already a dep
            soup = BeautifulSoup(html, "html.parser")
            for e in css_extractors:
                name = e.get("name") or ""
                sel = e.get("selector") or ""
                if not name or not sel:
                    continue
                try:
                    node = soup.select_one(sel)
                    out[name] = (node.get_text(strip=True) if node else "")[:1000]
                except Exception:  # noqa: BLE001
                    out[name] = ""
        except ImportError:
            pass

    if xpath_extractors:
        try:
            from lxml import html as lx  # lazy import — heavier dep
            tree = lx.fromstring(html.encode("utf-8", errors="replace"))
            for e in xpath_extractors:
                name = e.get("name") or ""
                sel = e.get("selector") or ""
                if not name or not sel:
                    continue
                try:
                    matches = tree.xpath(sel)
                    if not matches:
                        out[name] = ""
                        continue
                    first = matches[0]
                    if hasattr(first, "text_content"):
                        out[name] = (first.text_content() or "").strip()[:1000]
                    else:
                        out[name] = str(first).strip()[:1000]
                except Exception:  # noqa: BLE001
                    out[name] = ""
        except ImportError:
            pass

    return out


# ── C.4 — Readability + spelling ──────────────────────────────────


_SENTENCE_END = re.compile(r"[.!?]+")
_WORD = re.compile(r"\b[A-Za-z]+\b")
_VOWEL_GROUP = re.compile(r"[aeiouyAEIOUY]+")


def _syllables(word: str) -> int:
    """Cheap Flesch-grade syllable approximation: count vowel groups,
    subtract trailing silent 'e'. Fast, deterministic, no NLTK."""
    word = word.lower().strip()
    if not word:
        return 0
    groups = len(_VOWEL_GROUP.findall(word))
    if word.endswith("e") and groups > 1:
        groups -= 1
    return max(1, groups)


def _flesch(text: str) -> tuple[float, float, int, int]:
    """Flesch Reading Ease + Flesch-Kincaid Grade Level.
    Returns (flesch_score, grade_level, word_count, sentence_count)."""
    words = _WORD.findall(text or "")
    word_count = len(words)
    sentences = [s for s in _SENTENCE_END.split(text or "") if s.strip()]
    sentence_count = max(1, len(sentences))
    if word_count == 0:
        return (0.0, 0.0, 0, 0)
    total_syllables = sum(_syllables(w) for w in words)
    words_per_sent = word_count / sentence_count
    syll_per_word = total_syllables / word_count
    flesch = 206.835 - 1.015 * words_per_sent - 84.6 * syll_per_word
    grade = 0.39 * words_per_sent + 11.8 * syll_per_word - 15.59
    return (round(flesch, 2), round(grade, 2), word_count, sentence_count)


def readability_signals_from(text: str, *, spell_check: bool = True) -> dict:
    """Compute Flesch score, grade level, word + sentence counts,
    spelling errors (capped sample of 20).

    Spell-check is opt-out (default on) — pyspellchecker is small
    and pure-Python. English-only for v1; multilingual support
    needs LanguageTool which is out of scope.
    """
    flesch, grade, word_count, sentence_count = _flesch(text or "")
    out = {
        "flesch_score": flesch,
        "grade_level": grade,
        "readable_word_count": word_count,
        "readable_sentence_count": sentence_count,
        "spelling_error_count": 0,
        "spelling_errors": [],
    }
    if not spell_check or word_count == 0:
        return out

    try:
        from spellchecker import SpellChecker  # type: ignore
    except ImportError:
        return out

    try:
        spell = SpellChecker(distance=1)  # distance=1 → fewer false positives
        # Sample at most 2000 words — full-page check is too slow on
        # long pages and adds little signal once 2k words are clean.
        words = [w for w in _WORD.findall(text or "")[:2000] if 3 <= len(w) <= 20]
        unknown = spell.unknown([w.lower() for w in words])
        # pyspellchecker flags every proper noun and abbreviation;
        # filter ALL-CAPS-only words (likely acronyms) and capitalised
        # mid-sentence words (likely names) to keep noise down.
        filtered = []
        for w in unknown:
            if w.isupper():
                continue
            filtered.append(w)
        out["spelling_error_count"] = len(filtered)
        out["spelling_errors"] = sorted(filtered)[:20]
    except Exception:  # noqa: BLE001
        pass

    return out
