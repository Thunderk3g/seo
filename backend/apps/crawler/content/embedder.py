"""Embed-all-pages pipeline.

For each crawled page:
  1. Pull visible text (title + meta + body_text + h1 if available)
  2. Chunk at ~500-char windows
  3. Encode each chunk with MiniLM → 384-dim float32
  4. UPSERT into crawler_pageembedding (one row per chunk)
  5. Classification copy (products, page_type, confidence) is denormalised
     so the similarity API doesn't need to re-classify per query

Re-runs are incremental — existing chunks with unchanged text are skipped.
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.db import connection, transaction

log = logging.getLogger(__name__)


CHUNK_SIZE = 500   # characters, not tokens (rough approximation for English)
CHUNK_OVERLAP = 50


def chunk_text(text: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sliding-window chunker. Returns at least one chunk for any
    non-empty text. Conservative — splits on chars not tokens, so a
    little overshoot on tokens is fine."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _visible_text(page) -> str:
    """Concatenate the searchable fields from a CrawlerPageResult."""
    parts = [
        page.title or "",
        page.meta_description or "",
        page.body_text or "",   # may be empty for legacy crawls
    ]
    return " ".join(p for p in parts if p).strip()


def embed_snapshot(snapshot, *, force: bool = False, verbose: bool = False) -> dict:
    """Embed every page in a CrawlSnapshot. Returns counters dict.

    ``force`` re-embeds even pages that already have current chunks.
    """
    from sentence_transformers import SentenceTransformer  # lazy
    from ..models import CrawlerPageResult, PageEmbedding
    from .pipeline import classify_row
    from . import _minilm_path  # local helper, falls back to HF hub id

    log.info("loading MiniLM…")
    model = SentenceTransformer(_minilm_path())

    pages = (
        CrawlerPageResult.objects
        .filter(snapshot=snapshot, status_code="200")
    )

    counters = {
        "pages_seen": 0, "pages_embedded": 0, "pages_skipped": 0,
        "chunks_written": 0,
    }

    for page in pages.iterator():
        counters["pages_seen"] += 1

        if not force and PageEmbedding.objects.filter(page=page).exists():
            counters["pages_skipped"] += 1
            continue

        text = _visible_text(page)
        if not text:
            counters["pages_skipped"] += 1
            continue

        chunks = chunk_text(text)
        if not chunks:
            counters["pages_skipped"] += 1
            continue

        # Classify the page once (same labels for every chunk).
        # `classify_row` expects a dict — synthesise from the ORM page.
        page_row = {
            "url": page.url, "title": page.title or "",
            "meta_description": page.meta_description or "",
            "jsonld_types": page.jsonld_types or [],
        }
        cls = classify_row(page_row)
        products = [p["label"] for p in cls.get("products", [])]
        page_type = cls.get("page_type", "other")
        confidence = cls.get("page_type_confidence", 0.0)

        # Encode all chunks in one batch — much faster than per-chunk.
        vectors = model.encode(chunks, normalize_embeddings=True)

        with transaction.atomic():
            # Clean slate per page for this snapshot if force was on
            if force:
                PageEmbedding.objects.filter(page=page).delete()
            for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                emb = PageEmbedding.objects.create(
                    page=page,
                    chunk_idx=idx,
                    chunk_text=chunk[:1000],
                    embedding_json=vec.tolist(),
                    products=products,
                    page_type=page_type,
                    confidence=float(confidence),
                )
                # Set the pgvector column via raw SQL (Django ORM can't
                # write to it without a custom field). The literal is
                # pgvector text format: "[0.1,0.2,…]".
                vec_literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
                with connection.cursor() as cur:
                    cur.execute(
                        "UPDATE crawler_pageembedding SET embedding = %s::vector "
                        "WHERE id = %s",
                        [vec_literal, emb.id],
                    )
                counters["chunks_written"] += 1

        counters["pages_embedded"] += 1
        if verbose:
            log.info("embedded %s (%d chunks)", page.url, len(chunks))

    return counters
