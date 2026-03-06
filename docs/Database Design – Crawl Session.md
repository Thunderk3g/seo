# Database Design – Crawl Session Storage Architecture

## Overview
This document defines the database storage architecture for a crawler-driven website intelligence system. The database is designed around a **session-based crawling model** where each crawl (daily or on-demand) is stored as an independent snapshot of the website.

> **Core Principle:**
> *One Crawl = One Session = One Complete Snapshot of Website State*

This architecture enables historical comparison, change tracking, AI analysis, and GSC-like dashboard reporting.

---

## 1. Core Storage Philosophy
The database is structured to support:
- **Daily full crawl sessions** (every 24 hours)
- **On-demand crawl sessions** (user-triggered)
- **URL-level inspection sessions**
- **Historical trend analysis**
- **Snapshot-based dashboard updates**

*Instead of overwriting crawl data, each session stores a versioned snapshot of the website at that specific time.*

---

## 2. High-Level Database Architecture
```text
Website
 └── Crawl Sessions (Daily / On-Demand / URL Inspection)
          ├── Pages (Per URL Intelligence)
          ├── URL Classifications (Coverage Buckets)
          ├── Links (Internal & External Graph)
          ├── Structured Data (Enhancements)
          └── Sitemap Data
```

Each data record is linked to a `crawl_session_id` to ensure full traceability and historical accuracy.

---

## 3. Crawl Session Model (Time-Based Snapshots)
### Concept
A crawl session represents a **complete crawling job** executed at a specific timestamp.

### Types of Crawl Sessions
1. **Scheduled Session:** Daily full crawl
2. **On-Demand Session:** Manual full crawl
3. **URL Inspection Session:** Single URL crawl

*This separation allows flexible crawling while maintaining clean historical records.*

---

## 4. Data Tables Reference

### Table: `websites`
**Purpose:** Stores the root domains being monitored by the crawler. Enables support for single-site or multi-site crawling systems.

| Field | Description |
| :--- | :--- |
| `id` | Unique website identifier |
| `domain` | Primary domain name |
| `created_at` | Timestamp of website registration |

---

### Table: `crawl_sessions` *(Core Table)*
**Purpose:** Acts as the central container for every crawl execution and snapshot.

> [REVISED] Extended with crawl coverage metrics for Googlebot/GSC-aligned reporting.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `UUID` | Unique crawl session identifier |
| `website_id` | `FK` | Reference to monitored website |
| `session_type` | `Enum` | `scheduled` / `on_demand` / `url_inspection` |
| `status` | `Enum` | `running` / `completed` / `failed` |
| `started_at` | `Timestamp` | Crawl start timestamp |
| `finished_at`| `Timestamp` | Crawl completion timestamp |
| `total_urls_discovered` | `Int` | Count of all URLs in the Discovered Pool. |
| `total_urls_queued` | `Int` | Count of URLs promoted to the Crawl Queue. [NEW] |
| `total_urls_crawled` | `Int` | Count of URLs that received an HTTP response. |
| `total_urls_rendered` | `Int` | Count of URLs that completed Phase 2 JS rendering. [NEW] |
| `total_index_eligible` | `Int` | Count of URLs classified as `index_eligible`. [NEW] |
| `total_excluded` | `Int` | Count of URLs in any exclusion state. [NEW] |
| `exclusion_breakdown` | `JSONB` | Per-state counts for excluded URLs (e.g., `{"blocked_by_robots": 12, "excluded_noindex": 5, ...}`). [NEW] |

**Design Benefits:**
- Enables historical crawl tracking
- Supports multiple crawl types
- Allows progress monitoring
- Powers time-based dashboard comparisons
- Provides aggregate crawl coverage metrics at the session level [NEW]

---

### Table: `pages` *(Per-URL Crawl Intelligence)*
**Purpose:** Stores structured intelligence for every crawled URL within a session.

> [REVISED] Extended with URL lifecycle state, discovery attribution, canonical resolution, and directory/template classification.

| Key Stored Signals | Description |
| :--- | :--- |
| `url` & `normalized_url` | The target URL and its normalized form |
| `http_status_code` | Response code (e.g., 200, 404, 301) |
| `final_url` | Destination after redirects |
| `crawl_depth` | Distance from the root or seed URL |
| `load_time` | Page load speed metrics |
| `content_size` | Size of the page content |
| `word_count` | Number of words extracted |
| `canonical_url` | Defined canonical tag URL |
| `canonical_resolved` | The crawler's truth-resolved canonical (may differ from `canonical_url`). [NEW] |
| `canonical_match` | Boolean. `true` if the declared canonical matches the resolved canonical. [NEW] |
| `indexability_signals`| Attributes like robots meta tags |
| `https_status` | Security protocol used |
| `page_hash` | Hash value for change detection |
| `crawl_timestamp` | Exact time the page was fetched |
| `url_lifecycle_state` | GSC-compatible lifecycle classification for this URL within the session (see table below). [NEW] |
| `discovery_source_first` | The initial mechanism that surfaced this URL (e.g., `sitemap`, `internal_link`, `canonical_tag`, `redirect`, `manual_seed`). [NEW] |
| `discovery_sources_all` | Ordered list (JSONB) of every distinct mechanism that has ever surfaced this URL across sessions. [NEW] |
| `directory_segment` | Extracted directory path for template/directory aggregation (e.g., `/blog/`, `/products/`). [NEW] |
| `page_template` | Inferred page template identifier based on structural similarity heuristics. [NEW] |

#### URL Lifecycle State Values [NEW]

The `url_lifecycle_state` field stores one of the following GSC-aligned states, derived exclusively from crawl signals:

| State Value | Description |
| :--- | :--- |
| `discovered_not_crawled` | URL exists in the Discovered Pool but was never fetched due to budget, priority, or politeness. |
| `crawled_not_indexed` | Page was fetched but has weak signals (thin content, deep depth, low inbound links). |
| `index_eligible` | Passes all checks: 200 status, indexable directives, unique canonical, sufficient content. |
| `duplicate_without_canonical` | Content hash matches another page, but no `rel=canonical` is declared. |
| `duplicate_canonical_mismatch` | Page declares a canonical, but the crawler resolved a different canonical. |
| `alternate_proper_canonical` | Page correctly points to another URL as its canonical. |
| `soft_404` | HTTP 200 with minimal content or error-like template. |
| `blocked_by_robots` | Disallowed by `/robots.txt`. |
| `excluded_noindex` | Contains `noindex` meta directive or `X-Robots-Tag`. |
| `redirected` | Returned a 3xx response. |
| `error_server` | Server returned 5xx or request timed out. |
| `not_found_404` | Server returned HTTP 404. |

> **Important Constraint:** `UNIQUE (crawl_session_id, url)`
> *This ensures the same URL can exist across different sessions to track historical page evolution without duplicates in a single session.*

---

### Table: `url_classifications` *(Coverage & Indexing Buckets)*
**Purpose:** Stores GSC-like classification states derived from crawler signals.

**Example Classifications:**
- Indexed Candidate
- Crawled – Currently Not Indexed
- Discovered – Not Crawled
- Redirected Page
- Not Found (404) & Soft 404
- Duplicate without Canonical / Alternate with Proper Canonical
- Excluded by Noindex / Blocked by Robots

**Benefits:** Powers Coverage Dashboard, enables indexing analysis, and provides explainable URL states.

---

### Table: `links` *(Internal & External Link Graph)*
**Purpose:** Stores the complete link graph extracted during crawling. Critical for large websites with high internal link counts.

| Key Data Points |
| :--- |
| Source URL |
| Target URL |
| Link type (internal / external) |
| Anchor text |
| Rel attributes (nofollow, sponsored, etc.) |
| Associated `crawl_session_id` |

**Use Cases:** Internal link analysis, orphan page detection, top linked pages tracking, external link reporting.

---

### Table: `structured_data` *(Enhancements Storage)*
**Purpose:** Stores detected structured data and enhancement signals.

> [REVISED] Extended with explicit validation state classification.

**Supported Schema Types:** Breadcrumb, FAQ, Product, Review, Video, Article.

| Key Fields | Description |
| :--- | :--- |
| `page_id` | Reference to the parent page record. |
| `schema_type` | Detected schema type (e.g., `FAQ`, `Product`, `Breadcrumb`). |
| `validation_state` | Explicit classification: `valid`, `warning`, or `invalid`. [NEW] |
| `validation_errors` | JSONB array of specific validation issues (e.g., missing required field, malformed value). [NEW] |
| `is_valid` | Legacy boolean field; retained for backward compatibility. |
| `error_message` | Human-readable error summary. |
| `detected_at` | Timestamp of detection. |

#### Structured Data Validation States [NEW]

| State | Definition |
| :--- | :--- |
| `valid` | Schema is syntactically correct, contains all required fields, and is eligible for rich results. |
| `warning` | Schema is parseable but has non-critical issues (e.g., recommended fields missing, deprecated properties used). |
| `invalid` | Schema has critical errors that prevent parsing or rich result eligibility (e.g., missing required `@type`, malformed JSON-LD). |

**Dashboard Impact:** Powers enhancement panels for breadcrumb validity, review snippets, unprocessable structured data warnings, and per-type validation summaries.

---

### Table: `sitemap_urls` *(Sitemap Intelligence)*
**Purpose:** Stores URLs discovered from sitemap files for comparison against actually crawled URLs.

| Stored Data |
| :--- |
| Sitemap URL source |
| Page URL listed in sitemap |
| `lastmod` timestamp |
| `crawl_session_id` |

**Use Cases:** Sitemap vs. crawl reconciliation, missing pages detection, orphan URL identification.

---

## 5. Crawler Strategy & Workflow

### On-Demand Crawl Storage Strategy
- **Full Site Crawl:** A new session is created with `type = on_demand`. All data is stored under that session while existing ones remain unchanged.
- **URL-Level Crawl:** A new session is created with `type = url_inspection`. Only that URL’s data is stored for instant debugging and analysis.

### Daily Scheduled Crawl Storage Strategy
1. Create new crawl session (`type = scheduled`).
2. Perform full intelligent crawl.
3. Store all page, link, and signal data under the session ID.
4. Mark session as completed.
5. Dashboard reads latest completed session as the current website state.

---

## 6. Operations & Data Management

### Historical Data & Snapshot Comparison
Session-based storage enables historical intelligence without overwriting past data. each crawl becomes a historical checkpoint.
- **Analysis Supported:** Day-over-day page changes, new vs. removed URLs, indexability trend tracking, and improvement impact analysis.

### Change Detection Strategy (Session-Based)
Each page stores a content hash (`page_hash`).
- **Workflow:** Compare `page_hash` between current and previous sessions --> Detect modified pages --> Trigger incremental recrawls --> Generate change insights.
- **Benefits:** Efficient crawling, faster updates, less redundant processing.

### Session-to-Session Intelligence [NEW]

Beyond content hash comparison, the system compares full page sets between consecutive sessions to detect structural changes:

| Detection Type | Logic | Significance |
| :--- | :--- | :--- |
| **Newly Discovered URLs** | URL present in Session N but absent in Session N-1. | New content published or new link paths discovered. |
| **Dropped URLs** | URL present in Session N-1 but absent in Session N (not discovered or not crawled). | Content removed, link path broken, or budget excluded. |
| **Status Regressions** | URL returned 200 in Session N-1 but 404/5xx in Session N. | Broken page or server instability. |
| **Status Recoveries** | URL returned 4xx/5xx in Session N-1 but 200 in Session N. | Fix deployed or transient issue resolved. |
| **Lifecycle State Transitions** | `url_lifecycle_state` changed between sessions (e.g., `index_eligible` --> `crawled_not_indexed`). | Quality degradation, directive changes, or canonical shifts. |
| **Canonical Drift** | `canonical_resolved` value changed between sessions. | The crawler selected a different canonical, indicating site structure changes. |

These comparisons enable the AI agents and the dashboard to surface actionable alerts such as *"32 previously indexed pages returned 404 in today's crawl"* or *"15 new product URLs discovered since yesterday."*

### Template and Directory Aggregation [NEW]

To enable cluster-level analysis (rather than individual URL noise), the database supports grouping metrics by page template and directory segment.

| Aggregation Dimension | Source | Example Use Case |
| :--- | :--- | :--- |
| **Directory Segment** | Extracted from the URL path (e.g., `/blog/`, `/products/category/`). Stored in `pages.directory_segment`. | "The `/blog/` directory accounts for 60% of discovered URLs but only 30% of index-eligible pages." |
| **Page Template** | Inferred from DOM structural fingerprinting (heading patterns, layout markers). Stored in `pages.page_template`. | "The product listing template has an average word count of 45 -- below the thin content threshold." |

**Aggregated Metrics per Group:**
- Total URLs discovered, crawled, rendered, index-eligible, and excluded.
- Average load time, content size, and word count.
- Dominant lifecycle state distribution.
- Structured data adoption rate (`valid` / `warning` / `invalid` counts).

This aggregation powers directory-level and template-level panels in the dashboard, mirroring how Google Search Console groups URLs by pattern for coverage reporting.

### Data Retention Strategy
To balance storage limits and analytical needs:
- Store recent sessions in full detail.
- Archive older sessions after a defined period.
- Maintain lightweight metadata for long-term trend analysis.

### Query Optimization Considerations
To support fast dashboard performance:
- Index `crawl_session_id` in all major tables.
- Index URL fields for quick lookups.
- Optimize link graph queries.
- Use batch retrieval for large datasets.

---

## 7. Crawl Coverage Metrics [NEW]

The database supports aggregate coverage reporting at the session level, enabling Googlebot/GSC-style dashboards that distinguish between discovery, crawling, rendering, and classification.

### Session-Level Coverage Report

| Metric | Source | Description |
| :--- | :--- | :--- |
| **Total Discovered** | `crawl_sessions.total_urls_discovered` | All URLs known to the system (Discovered Pool). |
| **Total Queued** | `crawl_sessions.total_urls_queued` | URLs promoted to the Crawl Queue by the priority gate. |
| **Total Crawled** | `crawl_sessions.total_urls_crawled` | URLs that received an HTTP response (Phase 1). |
| **Total Rendered** | `crawl_sessions.total_urls_rendered` | URLs that completed JavaScript rendering (Phase 2). |
| **Total Index-Eligible** | `crawl_sessions.total_index_eligible` | URLs classified as `index_eligible` by the lifecycle state model. |
| **Total Excluded** | `crawl_sessions.total_excluded` | URLs in any exclusion state, with per-state breakdown in `exclusion_breakdown`. |

### Lifecycle State Distribution Query Pattern

```sql
SELECT url_lifecycle_state, COUNT(*) AS url_count
FROM pages
WHERE crawl_session_id = :current_session_id
GROUP BY url_lifecycle_state
ORDER BY url_count DESC;
```

This query powers the Coverage panel, showing exactly how many URLs fall into each GSC-compatible state.

### Key Insight

> **Discovered does not equal Crawled, and Crawled does not equal Indexed.**
> The coverage metrics explicitly separate these stages, mirroring Google Search Console's reporting model where a site may have 10,000 discovered URLs, 7,000 crawled, and only 4,500 index-eligible.

---

## 8. Final Summary
The session-based database architecture provides a scalable and intelligent storage system for crawler-driven platforms. By creating a dedicated crawl session every 24 hours and separate sessions for on-demand crawls, the system maintains complete historical snapshots of website state. This design supports accurate dashboard reporting, change detection, URL classification, link intelligence, and AI-driven insights while ensuring data consistency, traceability, and long-term scalability for large-scale website monitoring systems.

> [EXPANDED] The architecture now includes:
> - GSC-compatible `url_lifecycle_state` per page record.
> - Discovery source attribution (`discovery_source_first`, `discovery_sources_all`).
> - Session-to-session intelligence: newly discovered URLs, dropped URLs, status regressions, and canonical drift.
> - Template and directory aggregation for cluster-level reporting.
> - Explicit structured data validation states (`valid`, `warning`, `invalid`).
> - Aggregate crawl coverage metrics at the session level.
