"""Phase E — Gap-closer detectors: LanguageTool grammar +
AXE color-contrast accessibility.

3 detectors:

  * grammar_errors_high          — > 5 grammar/typo findings via
                                   LanguageTool (replaces / augments
                                   the older spelling_errors_high
                                   from Phase C.4)
  * grammar_typos_only           — high typo count but no grammar
                                   errors — surfaces brand-term
                                   whitelist gaps without false-
                                   flagging the whole page
  * color_contrast_failures      — axe-core color-contrast rule
                                   reported at least one element
                                   below WCAG AA contrast ratio
"""
from __future__ import annotations

from .catalog import IssueDef, Severity, _is_ok, _to_int


def _row_dict(v):
    if isinstance(v, dict):
        return v
    if not v:
        return {}
    try:
        import json as _json
        parsed = _json.loads(str(v))
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _detect_grammar_errors_high(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("grammar_error_count")) > 5
    ]


def _detect_grammar_typos_only(rows: list[dict]) -> list[dict]:
    """Page has > 5 errors but ALL of them are TYPOS — likely a brand-
    name dictionary gap, not a content quality issue. Surface so the
    operator can extend the whitelist."""
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        if _to_int(r.get("grammar_error_count")) <= 5:
            continue
        cats = _row_dict(r.get("grammar_categories"))
        if not cats:
            continue
        only_typos = list(cats.keys()) == ["TYPOS"] and cats.get("TYPOS", 0) > 5
        if only_typos:
            out.append(r)
    return out


def _detect_color_contrast_failures(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("color_contrast_violations_count")) > 0
    ]


PHASE_E_ISSUES: tuple[IssueDef, ...] = (
    IssueDef(
        slug="grammar_errors_high",
        title="More than 5 grammar / typo findings (LanguageTool)",
        severity="warning",
        category="content",
        why=(
            "Grammar mistakes directly damage E-E-A-T — Google's "
            "Expertise, Experience, Authoritativeness, Trustworthiness "
            "quality signal. They also reduce CTR when they appear in "
            "the SERP snippet text."
        ),
        how_to_fix=(
            "See `grammar_errors` column for the per-finding category + "
            "suggested replacements. Run the page through LanguageTool "
            "(or the dashboard's grammar drill-in) and apply the fixes."
        ),
        detector=_detect_grammar_errors_high,
    ),
    IssueDef(
        slug="grammar_typos_only",
        title="Many \"typos\" found but all are TYPOS category",
        severity="notice",
        category="content",
        why=(
            "When every finding on a page is in the TYPOS bucket and "
            "nothing else fires, the likely cause is brand vocabulary "
            "(\"Bajaj\", \"AUM\", product names) not being in the "
            "spell-checker dictionary, not real content quality issues."
        ),
        how_to_fix=(
            "Add Bajaj-specific brand terms to the LanguageTool user "
            "dictionary (or extend the project's brand-term whitelist) "
            "so they stop being flagged. Re-run the audit."
        ),
        detector=_detect_grammar_typos_only,
    ),
    IssueDef(
        slug="color_contrast_failures",
        title="Color-contrast WCAG failure (AA threshold)",
        severity="error",
        category="compliance",
        why=(
            "Text below WCAG AA contrast (4.5:1 for normal text, 3:1 "
            "for large text) is hard to read for users with low vision "
            "and fails WCAG SC 1.4.3. axe-core measured the rendered "
            "foreground/background colors and computed the actual "
            "contrast ratio — see `color_contrast_violations` for the "
            "element selectors + computed ratio."
        ),
        how_to_fix=(
            "Increase the foreground/background contrast (typically by "
            "darkening text or lightening backgrounds) until the "
            "computed ratio passes 4.5:1. The dashboard surfaces the "
            "exact CSS selector and current ratio per element."
        ),
        detector=_detect_color_contrast_failures,
    ),
)
