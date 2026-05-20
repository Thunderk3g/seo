"""Scrapy item pipelines for the crawler.

Phase 3d ships a single pipeline (``CsvDualWritePipeline``) that funnels
every successful item through the existing ``storage.csv_writer.append``
helper so the Phase 3c dual-write to Postgres + CSV WAL flow is reused
unchanged. Adding more pipelines (e.g., JSONL event log in Phase 3e)
is a one-line addition to the spider's ITEM_PIPELINES dict.
"""
from .csv_dual_write import CsvDualWritePipeline

__all__ = ["CsvDualWritePipeline"]
