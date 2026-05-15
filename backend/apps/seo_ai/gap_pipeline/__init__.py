"""Phase-3 gap detection pipeline.

Six sequential stages, each writing transparent intermediate data the UI
renders as its own panel — so users see *the queries we asked*, *what
each LLM answered*, *what the SERP returned*, *which 10 competitors won
the aggregation*, *what we crawled on each*, and only at the end *where
we lag*.

Stages:
    1. query_synthesis   — Groq LLM synthesises 20-30 queries from
                            domain + SEMrush keywords (ours + rivals').
    2. llm_search        — Each query × each enabled LLM provider with
                            web-search grounding where supported.
    3. serp_search       — Each query × each enabled SerpAPI engine.
    4. competitor_aggregation — Score domains across LLM + SERP signals
                            and pick the top 10.
    5. deep_crawl        — CompetitorCrawler against each of the 10 plus
                            our own domain (apples-to-apples).
    6. comparison        — Diff our crawl profile vs the rival median →
                            gap rows the UI shows last.

The orchestrator wires these together and updates ``GapPipelineRun.
stage_status`` after each stage so the polling UI can render live
progress.
"""
from .orchestrator import GapPipelineOrchestrator, STAGE_ORDER

__all__ = ["GapPipelineOrchestrator", "STAGE_ORDER"]
