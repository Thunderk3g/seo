"""Critic / Judge.

Second-pass agent that verifies every finding has at least one
``evidence_ref`` that resolves to a fact in the provided fact slice.
Anything unbacked gets flagged and dropped — agents are trained to
hallucinate URL slugs and round numbers when context is loose, and
this layer is the cheapest defence.

The critic is deliberately a *smaller* prompt: no narrative duties,
just verification. We still use the same provider (Groq runs fast and
costs little per call), but the model has a tighter system prompt and
no JSON-mode narrative output.
"""
from __future__ import annotations

from typing import Any

from .base import Agent

_SYSTEM_PROMPT = """You are a verification judge for SEO findings. You do
not write recommendations. You only decide whether each finding is
grounded in evidence the analyst was given.

You will receive:
- `findings`: a list of recommendations produced by an analyst.
- `valid_evidence_keys`: a flat list of `<namespace>:<key>` strings
  that the analyst was permitted to cite (e.g.
  `crawler:summary.thin_content_count`,
  `gsc:underperforming_queries[3].query`). This is the complete,
  authoritative list of valid references.

For each finding decide:
- `supported`: true if ALL of the finding's evidence_refs appear in
  `valid_evidence_keys`. If any evidence_ref is missing from the
  authoritative list, the finding is NOT supported.
- `notes`: short string explaining your decision when not supported.

Reply ONLY with one JSON object:

{
  "verdict": "accept" | "revise",
  "rejected_indices": [<int>, ...],
  "notes": "<≤500 chars overall summary>",
  "per_finding": [
    {"index": 0, "supported": true, "notes": "..."},
    ...
  ]
}

`verdict` is "revise" if any finding is unsupported. Be strict — when
in doubt, mark unsupported.""".strip()


_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["per_finding"],
    "properties": {
        "verdict": {"type": "string"},
        # We don't ask the model for rejected_indices — we compute it
        # ourselves from per_finding so format drift in arrays of ints
        # (gpt-oss-120b sometimes emits them as concatenated strings)
        # can't fail the run.
        "notes": {"type": "string"},
        "per_finding": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "supported"],
                "properties": {
                    # Accept either int or stringy-int; coerced in Python.
                    "index": {"type": ["integer", "string"]},
                    "supported": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
            },
        },
    },
}


class CriticAgent(Agent):
    name = "critic"
    system_prompt = _SYSTEM_PROMPT
    output_schema = _OUTPUT_SCHEMA

    def review(
        self,
        *,
        findings: list[dict[str, Any]],
        valid_evidence_keys: list[str],
    ) -> dict[str, Any]:
        # Send only the *minimal* fields of each finding the critic needs.
        # Full descriptions and recommendations balloon the prompt and the
        # critic only reads evidence_refs to make its call.
        slim = [
            {
                "index": i,
                "title": (f.get("title") or "")[:120],
                "evidence_refs": f.get("evidence_refs") or [],
            }
            for i, f in enumerate(findings)
        ]
        raw = self.call_model(
            {"findings": slim, "valid_evidence_keys": valid_evidence_keys},
            instruction=(
                "Judge each finding. For each finding emit a "
                "per_finding entry with its index and whether it is "
                "supported. Do NOT emit rejected_indices."
            ),
        ).payload
        # Derive rejected_indices ourselves so the run is robust to
        # array-of-int format drift. Coerce string indices to int.
        rejected: list[int] = []
        for entry in raw.get("per_finding") or []:
            if entry.get("supported"):
                continue
            idx = entry.get("index")
            try:
                rejected.append(int(idx))
            except (TypeError, ValueError):
                continue
        raw["rejected_indices"] = sorted(set(rejected))
        if "verdict" not in raw:
            raw["verdict"] = "revise" if rejected else "accept"
        return raw

    @staticmethod
    def filter_findings(
        findings: list[dict[str, Any]],
        verdict: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split findings into (accepted, rejected) per the critic verdict."""
        rejected_idx = set(verdict.get("rejected_indices") or [])
        accepted = [f for i, f in enumerate(findings) if i not in rejected_idx]
        rejected = [f for i, f in enumerate(findings) if i in rejected_idx]
        return accepted, rejected


# ── Generation-mode verifier (deterministic, no LLM round-trip) ──────


def verify_generation(
    proposal: dict[str, Any],
    evidence_dict: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically verify a content-generator proposal.

    The ContentWriterAgent emits proposals where every generated string
    carries a ``source_ref`` field — a key into the evidence dict the
    writer was given. This function walks the proposal, drops any
    entry whose ``source_ref`` doesn't resolve, and reports counts.

    Why deterministic instead of LLM-judged: source-reference lookup is
    a pure string check. Routing it through Groq would add ~1.5 s + a
    rate-limit slot for zero added rigor. We use the LLM judge for
    findings (semantic verification) but not for generation (mechanical
    reference check).

    Proposal shape this function understands (writer's contract):

        {
          "proposed_title": {"text": ..., "source_ref": "our:title"},
          "proposed_meta_description": {"text": ..., "source_ref": ...},
          "proposed_headings": [
              {"level": 2, "text": "...", "source_ref": "their:icicilife.com:headings[3]"},
              ...
          ],
          "proposed_internal_links": [
              {"anchor": "...", "target_url": "...", "source_ref": "..."},
              ...
          ],
          ...
        }

    Returns:

        {
          "accepted": int,            # count of strings whose source_ref resolved
          "rejected": int,            # count dropped
          "rejected_items": [{path, source_ref, reason}, ...],
          "filtered": <copy of proposal with unbacked items removed>,
        }

    Any entry without a ``source_ref`` is treated as unbacked. Empty
    or whitespace-only ``source_ref`` likewise.
    """
    accepted = 0
    rejected_items: list[dict[str, Any]] = []
    valid_keys = set(evidence_dict.keys()) if evidence_dict else set()

    def _check(item: Any, path: str) -> bool:
        """True if item.source_ref resolves; otherwise records rejection."""
        if not isinstance(item, dict):
            rejected_items.append({
                "path": path,
                "source_ref": None,
                "reason": "not a dict",
            })
            return False
        ref = (item.get("source_ref") or "").strip()
        if not ref:
            rejected_items.append({
                "path": path,
                "source_ref": "",
                "reason": "missing source_ref",
            })
            return False
        if ref not in valid_keys:
            rejected_items.append({
                "path": path,
                "source_ref": ref,
                "reason": "source_ref not in evidence",
            })
            return False
        return True

    filtered: dict[str, Any] = {}

    # Scalar generated fields.
    for key in ("proposed_title", "proposed_meta_description"):
        val = proposal.get(key)
        if val is None:
            continue
        if _check(val, key):
            filtered[key] = val
            accepted += 1

    # List generated fields — preserve only the entries that verify.
    # Includes RevampWriter additions: proposed_body_sections,
    # proposed_faq, proposed_ctas, tech_recommendations. Each is a list
    # of dicts; the source_ref check is identical regardless of the
    # surrounding shape (heading text, FAQ pair, CTA copy, tech finding).
    list_keys = (
        "proposed_headings",
        "proposed_internal_links",
        "proposed_body_sections",
        "proposed_faq",
        "proposed_ctas",
        "tech_recommendations",
    )
    for key in list_keys:
        items = proposal.get(key) or []
        kept: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            if _check(item, f"{key}[{i}]"):
                kept.append(item)
                accepted += 1
        if kept:
            filtered[key] = kept

    # Carry rationale + any future fields through unchanged. This is
    # where ``improved_html``, ``improved_markdown``,
    # ``competitor_gap_summary``, ``overall_rationale`` flow — they
    # don't carry their own ``source_ref`` because they're aggregate
    # outputs derived from many evidence keys.
    for key, val in proposal.items():
        if key in filtered or key in (
            "proposed_title", "proposed_meta_description",
            *list_keys,
        ):
            continue
        filtered[key] = val

    return {
        "accepted": accepted,
        "rejected": len(rejected_items),
        "rejected_items": rejected_items,
        "filtered": filtered,
    }
