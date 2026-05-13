"""BFS crawl engine sub-package — ported from crawler-engine/app/crawler/.

Modules:
  * url_utils — URL canonicalization, scope/extension filters, trap detection
  * robots    — robots.txt fetch + parse, can_fetch / crawl_delay
  * sitemap   — recursive sitemap.xml / sitemap-index / .xml.gz harvest
  * fetcher   — one URL -> (result row, links), retry/backoff
  * parser    — HTML -> title, word count, navigable links, console-error hints
  * engine    — top-level run_crawl() thread-pool BFS loop
"""
