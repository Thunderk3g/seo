"""Sentiment scoring for brand mention snippets.

Uses the existing Groq LLM provider (free tier — Llama 3 70B is cheap
on token cost and free on Groq's tier). Batches snippets in groups of
20 per prompt to keep call count low: a daily run of 100 fresh
mentions = 5 Groq calls = ~10 seconds of latency, well within free
quota.

Sentiment is one of {positive, neutral, negative} with a confidence
0.0-1.0. Confidence below ``MIN_CONFIDENCE`` (default 0.6) is treated
as ``neutral`` so we don't flag noise as negative.

Failure modes (all degrade gracefully):
  * Groq unavailable / not configured → return ``unscored`` for every
    item. The orchestrator persists rows with ``sentiment=unscored``
    so the UI can show them behind an "unscored" badge.
  * Groq returns malformed JSON → log once, score remaining items as
    ``unscored`` for that batch only.
  * Single snippet is too long → truncate to 500 chars before
    scoring. Token-rich blogs still get a sentiment, just based on
    the lead paragraph.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.conf import settings

from ...models import MentionSentiment

log = logging.getLogger("apps.seo_ai.adapters.brand_mentions.sentiment")

MIN_CONFIDENCE = 0.6
BATCH_SIZE = 20
SNIPPET_MAX_CHARS = 500


@dataclass
class SentimentScore:
    sentiment: str  # one of MentionSentiment values
    confidence: float


_PROMPT_TEMPLATE = """You are a brand-sentiment classifier for an Indian \
life-insurance company (Bajaj Life Insurance, formerly Bajaj Allianz Life).

For each numbered snippet below, decide whether the *overall tone toward \
Bajaj specifically* is POSITIVE, NEGATIVE, or NEUTRAL.

Be conservative — only POSITIVE/NEGATIVE when the language clearly indicates \
opinion or sentiment about Bajaj. Articles that merely mention Bajaj alongside \
many other insurers are NEUTRAL. Claim-settlement complaints, agent issues, \
or product praise are clear signals.

Return a strict JSON array — one object per snippet in the same order, with \
keys "sentiment" (one of "positive","neutral","negative") and "confidence" \
(float 0.0-1.0). No prose, no explanation, no markdown.

Snippets:
{snippets}

JSON array:"""


def score_sentiments(snippets: list[str]) -> list[SentimentScore]:
    """Score every snippet in order. Returns a list the same length as
    the input. ``unscored`` is returned for any item that can't be
    classified (Groq off, parse error, etc.).

    Inputs may be empty strings — we score those as ``neutral`` /
    confidence 0.0 without burning a token.
    """
    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    if not snippets:
        return []
    if not cfg.get("groq_sentiment_enabled", True):
        return [SentimentScore(MentionSentiment.UNSCORED, 0.0) for _ in snippets]

    try:
        from ...llm.provider import get_provider
    except ImportError as exc:
        log.info("sentiment: LLM provider not importable (%s)", exc)
        return [SentimentScore(MentionSentiment.UNSCORED, 0.0) for _ in snippets]

    try:
        provider = get_provider()
    except Exception as exc:  # noqa: BLE001
        log.info("sentiment: LLM provider init failed (%s)", exc)
        return [SentimentScore(MentionSentiment.UNSCORED, 0.0) for _ in snippets]

    out: list[SentimentScore] = [
        SentimentScore(MentionSentiment.UNSCORED, 0.0) for _ in snippets
    ]
    # Trim each snippet defensively + drop empties (they keep their
    # default neutral score).
    indexed = [
        (i, (s or "").strip()[:SNIPPET_MAX_CHARS])
        for i, s in enumerate(snippets)
    ]
    work_items = [(i, s) for i, s in indexed if s]

    for batch_start in range(0, len(work_items), BATCH_SIZE):
        batch = work_items[batch_start:batch_start + BATCH_SIZE]
        numbered = "\n".join(
            f"{n+1}. {text}" for n, (_, text) in enumerate(batch)
        )
        prompt = _PROMPT_TEMPLATE.format(snippets=numbered)
        try:
            resp = provider.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            log.info("sentiment batch failed: %s", exc)
            continue

        text = (getattr(resp, "content", "") or "").strip()
        parsed = _safe_parse_json_array(text)
        if not parsed or len(parsed) != len(batch):
            log.info(
                "sentiment: batch parse mismatch — expected %d, got %s",
                len(batch),
                len(parsed) if parsed else "none",
            )
            continue

        for (orig_idx, _), entry in zip(batch, parsed):
            label = _normalise_label(entry.get("sentiment"))
            try:
                conf = float(entry.get("confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if label != MentionSentiment.NEUTRAL and conf < MIN_CONFIDENCE:
                label = MentionSentiment.NEUTRAL
            out[orig_idx] = SentimentScore(label, max(0.0, min(1.0, conf)))

    return out


def _normalise_label(raw) -> str:
    s = (str(raw) or "").strip().lower()
    if s.startswith("pos"):
        return MentionSentiment.POSITIVE
    if s.startswith("neg"):
        return MentionSentiment.NEGATIVE
    if s.startswith("neu"):
        return MentionSentiment.NEUTRAL
    return MentionSentiment.UNSCORED


def _safe_parse_json_array(text: str) -> list[dict] | None:
    """Groq is set to JSON-object mode, so the response may be:
      * a top-level array
      * an object wrapping the array under a key
      * text containing a fenced-code-block of JSON
    Try each in order."""
    if not text:
        return None
    candidates: list[str] = [text]
    if text.startswith("```"):
        stripped = text.strip("`").strip()
        # Drop a leading "json" language tag if present.
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        candidates.append(stripped)
    for c in candidates:
        try:
            data = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            for key in ("snippets", "items", "results", "data", "scores"):
                v = data.get(key)
                if isinstance(v, list):
                    return [d for d in v if isinstance(d, dict)]
            # Single-snippet shape (rare): {sentiment: x, confidence: y}
            if "sentiment" in data:
                return [data]
    return None
