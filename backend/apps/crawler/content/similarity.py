"""Similarity search over pgvector embeddings.

All queries use cosine distance (`<=>` operator). HNSW index makes
top-k retrieval fast even at 100k+ chunks.
"""
from __future__ import annotations

from django.db import connection


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def similar_to_url(url: str, *, top_k: int = 10,
                   product: str | None = None,
                   page_type: str | None = None,
                   exclude_self: bool = True) -> list[dict]:
    """Find the top-k pages most semantically similar to ``url``.

    Picks the URL's first chunk embedding as the query vector. Returns
    deduped pages (one row per URL, taking the best-scoring chunk).
    """
    sql = """
      WITH q AS (
        SELECT embedding
        FROM crawler_pageembedding pe
        JOIN crawler_crawlerpageresult p ON pe.page_id = p.id
        WHERE p.url = %s AND pe.chunk_idx = 0
        LIMIT 1
      )
      SELECT
        p.url, p.title, p.page_type, pe.products, pe.page_type AS chunk_page_type,
        MIN(pe.embedding <=> (SELECT embedding FROM q)) AS distance
      FROM crawler_pageembedding pe
      JOIN crawler_crawlerpageresult p ON pe.page_id = p.id
      WHERE (SELECT embedding FROM q) IS NOT NULL
        {exclude_clause}
        {product_clause}
        {pt_clause}
      GROUP BY p.url, p.title, p.page_type, pe.products, pe.page_type
      ORDER BY distance ASC
      LIMIT %s
    """
    params: list = [url]
    exclude_clause = "AND p.url <> %s" if exclude_self else ""
    if exclude_self:
        params.append(url)
    product_clause = ""
    if product:
        product_clause = "AND pe.products @> %s::jsonb"
        import json
        params.append(json.dumps([product]))
    pt_clause = ""
    if page_type:
        pt_clause = "AND pe.page_type = %s"
        params.append(page_type)
    params.append(top_k)

    formatted = sql.format(
        exclude_clause=exclude_clause,
        product_clause=product_clause,
        pt_clause=pt_clause,
    )
    with connection.cursor() as cur:
        cur.execute(formatted, params)
        cols = [c[0] for c in cur.description]
        return [
            {**dict(zip(cols, row)), "similarity": round(1 - float(row[-1]), 4)}
            for row in cur.fetchall()
        ]


def similar_to_query(query: str, *, top_k: int = 10,
                     product: str | None = None,
                     page_type: str | None = None) -> list[dict]:
    """Free-text similarity. Embeds the query string once, then
    pgvector cosine-searches. The text agent's primary retrieval tool."""
    from sentence_transformers import SentenceTransformer
    from . import _minilm_path
    model = SentenceTransformer(_minilm_path())
    vec = model.encode([query], normalize_embeddings=True)[0]
    vec_lit = _vec_literal(vec)

    sql = """
      SELECT p.url, p.title, p.page_type, pe.products, pe.chunk_text,
             MIN(pe.embedding <=> %s::vector) AS distance
      FROM crawler_pageembedding pe
      JOIN crawler_crawlerpageresult p ON pe.page_id = p.id
      WHERE pe.embedding IS NOT NULL
        {product_clause}
        {pt_clause}
      GROUP BY p.url, p.title, p.page_type, pe.products, pe.chunk_text
      ORDER BY distance ASC
      LIMIT %s
    """
    params: list = [vec_lit]
    product_clause = ""
    if product:
        product_clause = "AND pe.products @> %s::jsonb"
        import json
        params.append(json.dumps([product]))
    pt_clause = ""
    if page_type:
        pt_clause = "AND pe.page_type = %s"
        params.append(page_type)
    params.append(top_k)

    formatted = sql.format(
        product_clause=product_clause,
        pt_clause=pt_clause,
    )
    with connection.cursor() as cur:
        cur.execute(formatted, params)
        cols = [c[0] for c in cur.description]
        return [
            {**dict(zip(cols, row)), "similarity": round(1 - float(row[-1]), 4)}
            for row in cur.fetchall()
        ]
