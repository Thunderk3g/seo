"""Scrapy item pipelines for the SEO-AI side of the platform.

Currently exposes the competitor dual-write pipeline that persists
CompetitorSpider output to CrawlerPageResult rows tagged
``kind='competitor'``. Future pipelines (citation-density scorer,
content-diff against AEM, etc.) live alongside this module.
"""
from .competitor_postgres import CompetitorDualWritePipeline

__all__ = ["CompetitorDualWritePipeline"]
