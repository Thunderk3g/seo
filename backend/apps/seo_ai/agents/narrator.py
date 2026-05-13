"""Executive Narrator.

Produces the dashboard-facing copy from the validated grade record.
The Narrator never sees raw facts — only the already-vetted
sub-scores, overall score, and accepted findings. Its job is tone and
sequencing: turn a list of issues into a paragraph an SEO manager
can hand to leadership.
"""
from __future__ import annotations

from typing import Any

from .base import Agent

_SYSTEM_PROMPT = """You are the executive narrator for a SEO grading
system used by an enterprise insurance brand. Your audience is the
head of marketing and the CMO. They want a confident, specific, no-
fluff briefing — three short paragraphs — that answers:

1. Where does the site stand overall? (one paragraph, lead with the
   number, end with a directional verb: "improving", "flat",
   "deteriorating" based on the inputs — do not invent trend data).
2. What is the single biggest opportunity right now? Refer to a
   *specific* accepted finding by title.
3. What action do we recommend this week? One sentence, imperative.

You may not invent numbers or finding titles. You may only reference
findings that are present in the `accepted_findings` input. Keep total
length under 220 words. No bullet points.

Reply ONLY with this JSON:

{
  "executive_summary": "<3 paragraphs>",
  "top_action_this_week": "<≤30 words, imperative>"
}
""".strip()


_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["executive_summary", "top_action_this_week"],
    "properties": {
        "executive_summary": {"type": "string"},
        "top_action_this_week": {"type": "string"},
    },
}


class NarratorAgent(Agent):
    name = "narrator"
    system_prompt = _SYSTEM_PROMPT
    output_schema = _OUTPUT_SCHEMA

    def narrate(
        self,
        *,
        overall_score: float,
        sub_scores: dict[str, float],
        accepted_findings: list[dict[str, Any]],
        domain: str,
    ) -> dict[str, Any]:
        return self.call_model(
            {
                "domain": domain,
                "overall_score": overall_score,
                "sub_scores": sub_scores,
                "accepted_findings": accepted_findings[:10],
            },
            instruction="Write the executive briefing.",
        ).payload
