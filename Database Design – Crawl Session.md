# Database Design – Crawl Session Storage Architecture

## Overview

This document defines the database storage architecture for a crawler-driven website intelligence system. The database is designed around a session-based crawling model where each crawl (daily or on-demand) is stored as an independent snapshot of the website.

Core Principle:

> One Crawl = One Session = One Complete Snapshot of Website State

This architecture enables historical comparison, change tracking, AI analysis, and GSC-like dashboard reporting.

---

# 1. Core Storage Philosophy

The database is structured to support:

* Daily full crawl sessions (every 24 hours)
* On-demand crawl sessions (user-triggered)
* URL-level inspection sessions
* Historical trend analysis
* Snapshot-based dashboard updates

Instead of overwriting crawl data, each session stores a versioned snapshot of the website at that specific time.

---

# 2. High-Level Database Architecture

```
Website
   └── Crawl Sessions (Daily / On-Demand / URL Inspection)
            ├── Pages (Per URL Intelligence)
            ├── URL Classifications (Coverage Buckets)
            ├── Links (Internal & External Graph)
            ├── Structured Data (Enhancements)
            └── Sitemap Data
```

Each data record is linked to a crawl_session_id to ensure full traceability and historical accuracy.

---

# 3. Crawl Session Model (Time-Based Snapshots)

## Concept

A crawl session represents a complete crawling job executed at a specific timestamp.

### Types of Crawl Sessions

* Scheduled Session (daily full crawl)
* On-Demand Session (manual full crawl)
* URL Inspection Session (single URL crawl)

This separation allows flexible crawling while maintaining clean historical records.

---

# 4. Table: websites

## Purpose

Stores the root domains being monitored by the crawler.

### Key Fields

* id: Unique website identifier
* domain: Primary domain name
* created_at: Timestamp of website registration

This enables support for single-site or multi-site crawling systems.

---

# 5. Table: crawl_sessions (Core Table)

## Purpose

Acts as the central container for every crawl execution and snapshot.

### Key Fields

* id (UUID): Unique crawl session identifier
* website_id: Reference to monitored website
* session_type: scheduled / on_demand / url_inspection
* status: running / completed / failed
* started_at: Crawl start timestamp
* finished_at: Crawl completion timestamp
* total_urls_discovered: Count of discovered URLs
* total_urls_crawled: Count of successfully crawled URLs

## Design Benefits

* Enables historical crawl tracking
* Supports multiple crawl types
* Allows progress monitoring
* Powers time-based dashboard comparisons

---

# 6. Table: pages (Per-URL Crawl Intelligence)

## Purpose

Stores structured intelligence for every crawled URL within a session.

### Key Stored Signals

* URL and normalized URL
* HTTP status code
* Final URL (after redirects)
* Crawl depth
* Load time
* Content size
* Word count
* Canonical URL
* Indexability signals
* HTTPS status
* Page hash (for change detection)
* Crawl timestamp

## Important Constraint

UNIQUE (crawl_session_id, url)

This ensures:

* Same URL can exist across different sessions
* Historical page evolution tracking
* No duplication within a single crawl session

---

# 7. Table: url_classifications (Coverage & Indexing Buckets)

## Purpose

Stores GSC-like classification states derived from crawler signals.

### Example Classifications

* Indexed Candidate
* Crawled – Currently Not Indexed
* Discovered – Not Crawled
* Redirected Page
* Not Found (404)
* Soft 404
* Duplicate without Canonical
* Alternate with Proper Canonical
* Excluded by Noindex
* Blocked by Robots

## Benefits

* Powers Coverage Dashboard
* Enables indexing analysis
* Provides explainable URL states

---

# 8. Table: links (Internal & External Link Graph)

## Purpose

Stores the complete link graph extracted during crawling.

### Key Data Points

* Source URL
* Target URL
* Link type (internal/external)
* Anchor text
* Rel attributes (nofollow, sponsored, etc.)
* Associated crawl_session_id

## Use Cases

* Internal link analysis
* Orphan page detection
* Top linked pages
* External link tracking

This table is critical for large websites with high internal link counts.

---

# 9. Table: structured_data (Enhancements Storage)

## Purpose

Stores detected structured data and enhancement signals.

### Supported Schema Types

* Breadcrumb
* FAQ
* Product
* Review
* Video
* Article

### Key Fields

* page_id
* schema_type
* is_valid
* error_message
* detected_at

## Dashboard Impact

Powers enhancement panels such as:

* Breadcrumb validity
* FAQ snippets
* Review snippets
* Unprocessable structured data

---

# 10. Table: sitemap_urls (Sitemap Intelligence)

## Purpose

Stores URLs discovered from sitemap files for comparison against crawled URLs.

### Stored Data

* Sitemap URL source
* Page URL listed in sitemap
* Lastmod timestamp
* crawl_session_id

## Use Cases

* Sitemap vs crawl reconciliation
* Missing pages detection
* Orphan URL identification

---

# 11. On-Demand Crawl Storage Strategy

## Full Site On-Demand Crawl

When a user triggers a full crawl:

* A new crawl_session is created with type = on_demand
* All crawled data is stored under that session
* Existing sessions remain unchanged

## URL-Level On-Demand Crawl

When a user inspects a single URL:

* A new session is created with type = url_inspection
* Only that URL’s data is stored
* Used for instant debugging and analysis

This ensures clean separation between scheduled and manual crawls.

---

# 12. Daily Scheduled Crawl Storage Strategy

## Process Flow

1. Create new crawl session (type = scheduled)
2. Perform full intelligent crawl
3. Store all page, link, and signal data under the session ID
4. Mark session as completed
5. Dashboard reads latest completed session as current website state

This creates a reliable daily snapshot of the entire website.

---

# 13. Historical Data & Snapshot Comparison

## Purpose

Session-based storage enables historical intelligence.

### Supported Analysis

* Day-over-day page changes
* New vs removed URLs
* Indexability trend tracking
* Structural changes over time
* Improvement impact analysis

Instead of overwriting data, each crawl becomes a historical checkpoint.

---

# 14. Change Detection Strategy (Session-Based)

Each page stores a content hash (page_hash).

### Workflow

* Compare page_hash between current and previous sessions
* Detect modified pages
* Trigger incremental recrawls
* Generate change insights

Benefits:

* Efficient crawling
* Faster updates
* Reduced redundant processing

---

# 15. Data Retention Strategy

Recommended retention approach:

* Store recent sessions in full detail
* Archive older sessions after defined period
* Maintain lightweight metadata for long-term trends

This balances storage cost and historical intelligence.

---

# 16. Query Optimization Considerations

To support fast dashboard performance:

* Index crawl_session_id in all major tables
* Index URL fields for quick lookup
* Optimize link graph queries
* Use batch retrieval for large datasets

Efficient indexing is critical for large websites with high URL and link volumes.

---

# 17. Final Summary

The session-based database architecture provides a scalable and intelligent storage system for crawler-driven platforms. By creating a dedicated crawl session every 24 hours and separate sessions for on-demand crawls, the system maintains complete historical snapshots of website state. This design supports accurate dashboard reporting, change detection, URL classification, link intelligence, and AI-driven insights while ensuring data consistency, traceability, and long-term scalability for large-scale website monitoring systems.
