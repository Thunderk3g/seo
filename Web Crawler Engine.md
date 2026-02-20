# Web Crawler Engine – Complete Specification (Crawler Only)

> **Focus:** Deep Crawling Architecture, Discovery, and Logic.  
> **Exclusions:** Backend Services, Databases, Dashboards, Frontend.

---

## Overview

This document defines the complete design and functionality of a production-grade web crawler engine. It focuses exclusively on crawling architecture, discovery, fetching, parsing, and crawl logic.

**Goal:**
> Discover → Crawl → Render → Parse → Extract Crawl Signals → Queue Next URLs

---

## 2. High-Level Crawler Flow

The engine follows a continuous loop from seed discovery to link extraction.

```mermaid
graph TD
    A[Seed URLs] --> B(Discovery Engine)
    B --> C{URL Frontier}
    C --> D[Fetcher]
    D --> E{JS Rendering?}
    E -- Yes --> F[Playwright/Renderer]
    E -- No --> G[Raw HTML Parser]
    F --> H[Signal Extraction]
    G --> H
    H --> I[Normalization & Filtering]
    I --> B
```

---

## 1. Core Purpose of the Web Crawler

A web crawler is an automated system that systematically browses and fetches web pages to:

*   **Discover** all URLs on a website
*   **Crawl** internal and external links
*   **Parse** HTML and rendered content
*   **Extract** crawl-level signals (links, metadata, assets)
*   **Monitor** site structure and changes over time

This crawler is designed for deep website crawling similar to search engine bots.

---

## 3. Seed Inputs (Starting Points)

The crawler begins with trusted seed sources to define the initial crawl surface.

| Source Type | Examples |
| :--- | :--- |
| **Primary Domain** | `https://example.com` |
| **Sitemaps** | `/sitemap.xml`, `/sitemap_index.xml` |
| **Rules** | `/robots.txt` |
| **Manual** | Custom URL lists |

---

## 4. URL Discovery Engine

### Purpose
Continuously discover new URLs from multiple crawl sources instead of relying only on hyperlinks.

### Discovery Sources
*   XML sitemaps & Sitemap index files
*   Internal anchor links (`<a href>`)
*   Canonical tags & Pagination links
*   Navigation menus & Footer links
*   JavaScript-rendered links & Redirect targets

### Responsibilities
*   **Extraction:** Identification of raw URLs.
*   **Normalization:** Path standardization.
*   **Filtering:** Removal of duplicates or non-crawlable paths.
*   **Scope Management:** Maintaining crawl within allowed domains.

---

## 5. URL Frontier (Crawl Queue System)

### Purpose
Acts as the brain of the crawler, managing which URLs to crawl and when.

### Key Functions
*   Maintain queue of pending URLs.
*   Prevent duplicate crawling via deduplication hashes.
*   Track crawl depth and assign priorities.
*   Support re-crawling logic for updated content.

### URL Object Structure
```json
{
  "url": "https://example.com/page",
  "depth": 2,
  "priority": 0.8,
  "source": "sitemap",
  "status": "pending"
}
```

---

## 6. Robots.txt Handling (Mandatory)

Ensure ethical and rule-compliant crawling by fetching `/robots.txt` before any page requests.

*   **Parse** disallowed paths.
*   **Respect** crawl-delay directives.
*   **Extract** sitemap locations declared in the file.
*   **User-Agent Rules:** Apply specific rules based on the crawler identity.

---

## 7. Sitemap Crawling System

Supporting multiple sitemap types for exhaustive discovery.

*   **Supported:** `sitemap.xml`, `sitemap_index.xml`, Image/Video sitemaps.
*   **Data Points:** Location (`loc`), Last Modified (`lastmod`), Change Frequency (`changefreq`), Priority.
*   **Special Handling:** Recursive crawling of child sitemaps in index files.

---

## 8. Fetcher Module (Page Downloader)

Download web pages and collect response-level signals.

*   **HTTP/HTTPS:** Full support for modern web protocols.
*   **Resilience:** Redirect handling, timeout management, and retry logic.
*   **Captured Data:** Status codes (200, 404, 500), Final URL, Response headers, Raw HTML, Latency.

---

## 9. JavaScript Rendering Layer (Dynamic Sites)

Handle modern websites built with Next.js, React, or Vue.

*   **Execution:** Full JS rendering for Single Page Applications (SPA).
*   **DOM Capture:** Extraction of dynamically injected links and content.
*   **Lazy Loading:** Scrolling or interacting to trigger lazy-loaded URL discovery.

---

## 10. Parser Module (HTML & DOM Analysis)

Extract crawl-relevant elements from fetched pages (Raw HTML or Rendered DOM).

*   **Metadata:** Title, Meta Description, Robots meta directives.
*   **Structure:** Headings (H1-H3), Canonical links.
*   **Assets:** Images (src/alt), Scripts, CSS files.
*   **Intelligence:** Structured data (JSON-LD, Schema) and main textual content.

---

## 11. Link Extraction Engine

*   **Internal:** Navigation, breadcrumbs, content, and footer links.
*   **External:** Outbound domain tracking and anchor text analysis.
*   **Classification:** Tagging links as Internal, External, Media, or Resource (PDF/ZIP).

---

## 12. URL Normalization & Filtering

*   **Normalization:** Remove fragments (#), standardize slashes, convert relative to absolute.
*   **Filtering:** Skip non-HTTP links (`mailto:`, `tel:`), duplicates, and query-heavy junk.

---

## 13. Breadth-First Search (BFS) and Coverage Strategy

Implementing BFS allows the engine to crawl reachable links on a website systematically. However, coverage is subject to specific technical and environmental conditions.

### Systematic Discovery
BFS visits all discovered URLs level by level (Homepage → Internal Links → Deeper Links). This approach systematically covers the entire site graph that is discoverable and accessible to the crawler.

### Coverage Limitations
BFS does not guarantee 100% coverage of every possible server-side link due to:
*   **Robots.txt Constraints:** Blocked paths and disallowed directories.
*   **Authentication Barriers:** Pages requiring login or gated access.
*   **Infinite URL Loops:** Dynamic pagination, calendar URLs, and complex query parameters.
*   **User Interactions:** Links generated only after specific events (clicks, forms).
*   **Orphan Pages:** Pages not linked internally that remain invisible unless listed in seeds or sitemaps.
*   **JS-Heavy Architectures:** Links hidden deep within JavaScript logic without proper DOM rendering.

### Enhancing Deep Coverage
To achieve maximum reach beyond basic BFS, the engine must integrate:
*   **Sitemap Crawling:** To capture orphan and hidden URLs.
*   **JS Rendering:** To extract dynamically injected links.
*   **URL Normalization & Deduplication:** To prevent redundant processing and infinite loops.
*   **Depth Limits & Loop Detection:** To manage crawl scope and prevent resource exhaustion.

---

## 14. Crawl Depth Management

*   **Rule Set:** Depth 0 (Homepage), Depth 1 (Navigation), Depth 2+ (Content).
*   **Logic:** Prevents infinite loops and infinite scrolling traps.

---

## 14. Crawl Politeness & Rate Limiting

*   **Ethics:** Respect robots.txt `crawl-delay`.
*   **Throttling:** Domain-based request limits to avoid server overload.
*   **Adaptability:** Backoff strategies on repeated failures.

---

## 15. Duplicate Detection & Change Detection

*   **Deduplication:** Maintain a set of visited/hashed URLs.
*   **Change Detection:** Content hash comparison to identify page updates.

---

## 16. Error Handling & Status Monitoring

*   Track 404s, 500s, timeouts, and redirect loops.
*   Log failures for potential retry cycles.

---

## 17. Asset & Resource Crawling (Advanced)

*   Detection and logging of Images, CSS, JS bundles, PDFs, and Fonts.
*   Helps in mapping the full site surface area.

---

## 18. Continuous Crawling Strategy

*   **Recrawl Logic:** Frequency based on priority and detected change signals.
*   **Hints:** Utilizing `lastmod` from sitemaps for scheduling.

---

## 19. Key Design Principles

*   Modular and Asynchronous architecture.
*   Ethical and Compliant (Robots/Sitemaps).
*   Scalable discovery pipeline for deep site mapping.

---

## 20. Final Summary

This web crawler engine is a deep, intelligent crawling system that:
*   Discovers URLs from multiple sources.
*   Fetches both static and JS-rendered pages.
*   Extracts comprehensive crawl signals.
*   Manages politeness and scheduling automatically.

The system is focused purely on **comprehensive, structured, and scalable web crawling.**

