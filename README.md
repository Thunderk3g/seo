# tanish-24-git-seo

Production-ready scalable Website Intelligence Platform consisting of a Web Crawler Engine, Multi-Agent AI System, GSC Integration, and a Session-Based Database.

---

## Googlebot/GSC Mirroring

This platform is designed to replicate the observable behaviors and classification logic of Google Search Console (GSC) without claiming actual Google indexing or ranking capabilities. The architecture mirrors how Googlebot discovers, crawls, renders, and classifies URLs.

### Core Architectural Parallels

| Google Concept | Platform Implementation |
| :--- | :--- |
| **Googlebot Discovery** | URLs enter a Discovered Pool from sitemaps, internal links, canonical tags, and redirects. Discovery does not guarantee crawling. |
| **Crawl Budget** | A Host Health and Adaptive Crawl Budget model throttles concurrency based on server latency, 5xx rates, and timeouts -- mirroring how Googlebot backs off from stressed servers. |
| **Two-Wave Rendering** | Phase 1 fetches raw HTML for immediate link extraction. Phase 2 defers JavaScript rendering to an asynchronous queue, matching Googlebot's known rendering delay. |
| **Canonical Resolution** | The `rel=canonical` tag is treated as a hint, not a directive. The crawler resolves true canonicals using redirects, internal link volume, content similarity, and sitemap inclusion. |
| **URL Inspection** | A high-priority bypass mode fetches, renders, and classifies a single URL on demand, producing a diagnostic payload identical in structure to GSC's URL Inspection tool. |
| **Coverage States** | Every URL receives a GSC-compatible lifecycle state (e.g., `Discovered -- Not Crawled`, `Crawled -- Currently Not Indexed`, `Duplicate -- Canonical Mismatch`, `Index-Eligible`). |

### Why Discovered Does Not Equal Crawled

Not every discovered URL is fetched. The transition from the Discovered Pool to the Crawl Queue is gated by:

- **Crawl Budget:** The session has a finite number of fetches. Low-priority URLs remain in the pool.
- **Priority Scoring:** A multi-variate formula (sitemap signal, inbound links, depth, freshness, historical change rate) ranks URLs. Only the top-scoring URLs are promoted.
- **Host Health:** If the target server degrades (high latency, 5xx errors), the crawler reduces or pauses requests.
- **Politeness:** `robots.txt` crawl-delay and domain concurrency limits restrict throughput.

URLs that remain unfetched at session end receive the state `Discovered -- Not Crawled`. This is intentional, measurable, and mirrors GSC's reporting behavior.

### Why Crawled Does Not Equal Indexed

A crawled URL is not automatically index-eligible. After fetching, URLs undergo canonical resolution and lifecycle state classification. A URL may be excluded due to:

- `noindex` directives (meta tag or `X-Robots-Tag` header).
- Duplicate content without a declared canonical.
- Crawler-resolved canonical mismatch (the crawler chose a different canonical than the declared tag).
- Thin or empty content producing a Soft 404 classification.
- Server errors (5xx) or client errors (404).

The Coverage dashboard explicitly separates Total Discovered, Total Crawled, Total Rendered, and Total Index-Eligible, matching GSC's funnel model.

### Documentation Reference

| Document | Key Sections |
| :--- | :--- |
| `Web Crawler Engine.md` | URL Lifecycle State Model, Two-Phase Crawling, Host Health, Canonical Clustering, URL Inspection Mode |
| `Crawling Strategies.md` | Frontier Priority Scoring, Sitemap vs Crawl Reconciliation, URL Pattern Trap Detection |
| `Database Design -- Crawl Session.md` | Lifecycle State Fields, Session-to-Session Intelligence, Crawl Coverage Metrics |
| `AI Agent Structure.md` | Indexing Intelligence (Canonical Clusters), GSC State Mapper Agent |
