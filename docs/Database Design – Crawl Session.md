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

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `UUID` | Unique crawl session identifier |
| `website_id` | `FK` | Reference to monitored website |
| `session_type` | `Enum` | `scheduled` / `on_demand` / `url_inspection` |
| `status` | `Enum` | `running` / `completed` / `failed` |
| `started_at` | `Timestamp` | Crawl start timestamp |
| `finished_at`| `Timestamp` | Crawl completion timestamp |
| `total_urls_discovered` | `Int` | Count of discovered URLs |
| `total_urls_crawled` | `Int` | Count of successfully crawled URLs |

**Design Benefits:**
- Enables historical crawl tracking
- Supports multiple crawl types
- Allows progress monitoring
- Powers time-based dashboard comparisons

---

### Table: `pages` *(Per-URL Crawl Intelligence)*
**Purpose:** Stores structured intelligence for every crawled URL within a session.

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
| `indexability_signals`| Attributes like robots meta tags |
| `https_status` | Security protocol used |
| `page_hash` | Hash value for change detection |
| `crawl_timestamp` | Exact time the page was fetched |

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

**Supported Schema Types:** Breadcrumb, FAQ, Product, Review, Video, Article.

| Key Fields |
| :--- |
| `page_id` |
| `schema_type` |
| `is_valid` |
| `error_message` |
| `detected_at` |

**Dashboard Impact:** Powers enhancement panels for breadcrumb validity, review snippets, unprocessable structured data warnings, etc.

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
- **Workflow:** Compare `page_hash` between current and previous sessions → Detect modified pages → Trigger incremental recrawls → Generate change insights.
- **Benefits:** Efficient crawling, faster updates, less redundant processing.

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

## 7. Final Summary
The session-based database architecture provides a scalable and intelligent storage system for crawler-driven platforms. By creating a dedicated crawl session every 24 hours and separate sessions for on-demand crawls, the system maintains complete historical snapshots of website state. This design supports accurate dashboard reporting, change detection, URL classification, link intelligence, and AI-driven insights while ensuring data consistency, traceability, and long-term scalability for large-scale website monitoring systems.
