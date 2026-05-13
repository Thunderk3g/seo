"""No ORM models — crawler-engine port uses CSV + JSON file storage.

Kept as an empty module so Django's app loader is happy. Crawl results
are written to ``settings.CRAWLER_DATA_DIR`` as append-only CSVs and a
checkpointed ``crawl_state.json``; reports are written to
``settings.CRAWLER_REPORTS_DIR`` as XLSX.
"""
