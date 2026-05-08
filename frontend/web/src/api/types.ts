// Types matching the actual DRF serializers in
// backend/apps/crawler/serializers.py. Hand-written until openapi-typescript
// is wired (DRF schema endpoint not yet exposed — see Day 5+).
//
// All primary keys are UUID strings (UUIDPrimaryKeyMixin). Day 1+ code MUST
// treat session/website/page IDs as strings, never numbers.

export type SessionType =
  | 'scheduled'
  | 'on_demand'
  | 'url_inspection';

export type SessionStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

// Matches CrawlConfigSerializer.
export interface CrawlConfig {
  max_depth: number;
  max_urls_per_session: number;
  concurrency: number;
  request_delay: number;
  request_timeout: number;
  max_retries: number;
  enable_js_rendering: boolean;
  respect_robots_txt: boolean;
  custom_user_agent: string;
}

// Matches WebsiteSerializer (read).
export interface Website {
  id: string;
  domain: string;
  name: string;
  is_active: boolean;
  include_subdomains: boolean;
  crawl_config: CrawlConfig | null;
  created_at: string;
  updated_at: string;
}

// Matches WebsiteCreateSerializer request body. The serializer normalises
// `domain` server-side; clients can send bare or scheme-prefixed domains.
export interface WebsiteCreate {
  domain: string;
  name?: string;
  is_active?: boolean;
  include_subdomains?: boolean;
  max_depth?: number;
  max_urls_per_session?: number;
  concurrency?: number;
}

// Matches CrawlSessionListSerializer.
export interface CrawlSessionListItem {
  id: string;
  website: string;
  website_domain: string;
  session_type: SessionType;
  status: SessionStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  total_urls_discovered: number;
  total_urls_crawled: number;
  total_urls_failed: number;
  max_depth_reached: number;
  avg_response_time_ms: number;
}

// Matches CrawlSessionDetailSerializer (extends list with extra fields).
export interface CrawlSessionDetail extends CrawlSessionListItem {
  total_urls_skipped: number;
  error_summary: Record<string, number>;
  target_url: string;
  target_path_prefix: string;
  created_at: string;
  updated_at: string;
}

// Matches PageListSerializer.
export interface PageListItem {
  id: string;
  url: string;
  http_status_code: number;
  title: string | null;
  crawl_depth: number;
  load_time_ms: number;
  word_count: number;
  source: string;
  is_https: boolean;
}

// Response shape from POST /websites/:id/crawl/.
export interface CrawlTriggeredResponse {
  message: string;
  task_id: string;
  website_id: string;
}

// DRF validation error shape: { field_name: ["error msg"] } or { detail: "msg" }.
export type DrfFieldErrors = Record<string, string[]>;

// DRF PageNumberPagination response shape.
export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// Activity-feed entry. Backend returns a merged list of:
//   - persisted CrawlEvent rows (lifecycle events)
//   - synthesized per-URL events from the Page table
// The shape is identical for both. `id` may be a UUID (for persisted rows)
// or a synthetic key like "page-<uuid>" for derived rows.
export type CrawlEventKind =
  | 'crawl'
  | 'discovery'
  | 'skip'
  | 'error'
  | 'blocked'
  | 'redirect'
  | 'session';

export interface CrawlEvent {
  id: string;
  timestamp: string; // ISO-8601
  kind: CrawlEventKind;
  url: string;
  message: string;
  metadata: Record<string, unknown>;
}

// ─────────────────────────────────────────────────────────────────
// Issues — derived by IssueService.derive_issues / get_issue_detail
// (backend/apps/crawl_sessions/services/issue_service.py).
// ─────────────────────────────────────────────────────────────────

export type IssueSeverity = 'error' | 'warning' | 'notice';

export interface IssueSummary {
  id: string;            // e.g. "broken-4xx", "missing-title"
  name: string;
  severity: IssueSeverity;
  description: string;
  count: number;
}

export interface IssueAffectedUrl {
  url: string;
  http_status_code: number | null;
  title: string;
  crawl_depth: number;
  load_time_ms: number | null;
}

export interface IssueDetail extends IssueSummary {
  affected_urls: IssueAffectedUrl[];
}

// ─────────────────────────────────────────────────────────────────
// Analytics — AnalyticsService.get_chart_data
// (backend/apps/crawl_sessions/services/analytics_service.py).
// All four datasets ship in one response.
// ─────────────────────────────────────────────────────────────────

export interface AnalyticsStatusEntry {
  label: '2xx' | '3xx' | '4xx' | '5xx' | 'unknown';
  count: number;
  color: string; // hex e.g. "#6ee7b7"
}

export interface AnalyticsDepthEntry {
  depth: number;
  count: number;
}

export interface AnalyticsResponseTimeEntry {
  bucket:
    | '0-100ms'
    | '100-250ms'
    | '250-500ms'
    | '500-1000ms'
    | '1000-2500ms'
    | '2500ms+';
  count: number;
}

export interface AnalyticsContentTypeEntry {
  label: 'html' | 'image' | 'css' | 'js' | 'font' | 'document' | 'other';
  count: number;
}

export interface AnalyticsCharts {
  status_distribution: AnalyticsStatusEntry[];
  depth_distribution: AnalyticsDepthEntry[];
  response_time_histogram: AnalyticsResponseTimeEntry[];
  content_type_distribution: AnalyticsContentTypeEntry[];
  total_pages: number;
}

// ─────────────────────────────────────────────────────────────────
// Exports — ExportService.list_exports / create_export
// (backend/apps/crawl_sessions/services/export_service.py).
// `kind` is one of the ExportRecord.KIND_* constants in
// backend/apps/crawl_sessions/models.py.
// ─────────────────────────────────────────────────────────────────

export type ExportKind =
  | 'urls.csv'
  | 'issues.xlsx'
  | 'sitemap.xml'
  | 'broken-links.csv'
  | 'redirects.csv'
  | 'metadata.json';

export interface ExportRecordSummary {
  id: string;
  kind: ExportKind;
  filename: string;
  content_type: string;
  row_count: number;
  size_bytes: number;
  generated_at: string; // ISO-8601
}

// ─────────────────────────────────────────────────────────────────
// Settings — SettingsService.get_settings / update_settings
// (backend/apps/crawler/services/settings_service.py:_to_dict).
// Endpoint: GET / PATCH /api/v1/settings/?website=<uuid>.
//
// `website_id` and `domain` are read-only (managed via website CRUD);
// every other key is editable. Server-side range validation lives in
// _VALIDATORS — clients should mirror these on inputs but rely on the
// server as the source of truth (400 with "field: reason" on failure).
// ─────────────────────────────────────────────────────────────────

export interface SettingsDict {
  // Read-only.
  website_id: string;
  domain: string;
  // Editable — Website fields.
  is_active: boolean;
  include_subdomains: boolean;
  // Editable — CrawlConfig fields.
  max_depth: number;             // 0..50
  max_urls_per_session: number;  // 1..1_000_000
  concurrency: number;           // 1..100
  request_delay: number;         // 0.0..60.0
  request_timeout: number;       // 1..300
  max_retries: number;           // 0..10
  enable_js_rendering: boolean;
  respect_robots_txt: boolean;
  custom_user_agent: string;     // ≤500 chars
  // Storage-only exclusion lists (engine enforcement is a follow-up).
  excluded_paths: string[];      // ≤100 entries, ≤200 chars each
  excluded_params: string[];     // ≤100 entries, ≤200 chars each
}

// PATCH body — any subset of the editable keys. The view layer drops
// unknown / read-only keys silently (PATCH semantics), but we keep the
// type tight so callers don't accidentally try to mutate read-only ones.
export type SettingsUpdate = Partial<Omit<SettingsDict, 'website_id' | 'domain'>>;

// ─────────────────────────────────────────────────────────────────
// Site tree — TreeService.build_tree
// (backend/apps/crawl_sessions/services/tree_service.py).
// Powers the Visualizations page. Recursive folder hierarchy where
// each node aggregates the URL counts of itself and its descendants.
// ─────────────────────────────────────────────────────────────────

export interface TreeNode {
  /** Path segment for this node, e.g. "products". The root node uses "/". */
  name: string;
  /** Full path from the site root, e.g. "/products/shoes". Root is "/". */
  path: string;
  /** Inclusive count: pages at this node + every descendant. */
  url_count: number;
  /** Pages whose path is exactly this node (excludes descendants). */
  direct_url_count: number;
  /** Children sorted by url_count desc, then name asc. */
  children: TreeNode[];
}

/**
 * Root payload returned by GET /sessions/<uuid>/tree/.
 * Identical to TreeNode but carries an extra `max_depth_reached` field
 * (deepest level with at least one page; root = 0).
 */
export interface SiteTree extends TreeNode {
  max_depth_reached: number;
}

// ─────────────────────────────────────────────────────────────────
// Links — flat link graph from LinkSerializer
// (backend/apps/crawler/serializers.py). Not consumed by the v1
// Visualizations page (force-graph viz cut), but typed here for
// future Day 4+ work.
// ─────────────────────────────────────────────────────────────────

export interface Link {
  source_url: string;
  target_url: string;
  link_type: string;
  anchor_text: string;
  rel_attributes: string;
  is_navigation: boolean;
}

// ─────────────────────────────────────────────────────────────────
// AI Insights — InsightsService.get_insights
// (backend/apps/ai_agents/services/insights_service.py).
// Day 5 surface; env-gated via ANTHROPIC_API_KEY on the backend.
// When `available === false`, the frontend renders the
// "AI insights are not configured" placeholder.
// ─────────────────────────────────────────────────────────────────

export type InsightSeverity = 'info' | 'warning' | 'critical';
export interface InsightHighlight {
  title: string;
  severity: InsightSeverity;
  body: string;
}
export interface InsightsResponse {
  available: boolean;
  session_id: string;
  summary: string;
  highlights: InsightHighlight[];
  model: string;
  cached: boolean;
  generated_at: string;
}

// ─────────────────────────────────────────────────────────────────
// Overview snapshot — OverviewService.get_overview
// (backend/apps/crawl_sessions/services/overview_service.py).
// Powers the Dashboard KPI strip, SEO Health gauge, and System
// Metrics card via GET /sessions/<uuid>/overview/.
// ─────────────────────────────────────────────────────────────────

export interface OverviewKpis {
  total_urls: number;   // discovered (frontier)
  crawled: number;      // successfully fetched
  pending: number;      // discovered but not yet crawled
  failed: number;       // 4xx / 5xx / network errors
  excluded: number;     // robots / rules / classification
}

export interface HealthReason {
  label: string;
  delta: number;        // signed: positive = added, negative = subtracted
}

export type HealthBand = 'good' | 'warn' | 'poor';

// Spec §5.4.1 Technical / Content / Performance breakdown. Each value is
// an independent 0..100 sub-score computed server-side; see
// backend/apps/crawl_sessions/services/overview_service.py::_compute_health
// for the predicate-by-predicate formulas.
export interface OverviewSubScores {
  technical: number;    // 0..100
  content: number;      // 0..100
  performance: number;  // 0..100
}

export interface OverviewHealth {
  score: number;        // 0..100, integer — index_eligible / crawled * 100
  band: HealthBand;     // >=80 'good', >=50 'warn', else 'poor'
  reasons: HealthReason[];
  // Optional for backwards-compat with older payloads. New backends
  // always populate this; the dashboard renders it when present.
  sub_scores?: OverviewSubScores;
}

export interface SystemMetrics {
  avg_response_time_ms: number;
  p95_response_time_ms: number | null;  // null when no pages yet
  median_depth: number;
  max_depth_reached: number;
  pages_with_issues: number;            // distinct URLs across all 12 categories
}

export interface OverviewSnapshot {
  session_id: string;
  session_status: SessionStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  kpis: OverviewKpis;
  health: OverviewHealth;
  system_metrics: SystemMetrics;
}

// ─────────────────────────────────────────────────────────────────
// Client-only user preferences — persisted to localStorage under the
// key `lattice.prefs` (spec §5.4.8/§5.4.9). Not sent to the backend;
// applied on mount and on change via CSS variables and body classes.
// ─────────────────────────────────────────────────────────────────

export interface LatticePrefs {
  accent: 'amber' | 'violet' | 'cyan' | 'emerald';
  density: 'comfortable' | 'compact';
  theme: 'dark' | 'light' | 'system';
}

// ─────────────────────────────────────────────────────────────────
// System host metrics — backend/apps/crawler/views_system_metrics.py
// (Spec §4.2). Powers the Dashboard's SystemMetricsCard via
// GET /api/v1/system/metrics/. Distinct from the SystemMetrics
// interface above (which carries crawl-perf metrics from
// OverviewService.get_overview).
// ─────────────────────────────────────────────────────────────────

export interface SystemHostMetrics {
  host: {
    cpu_percent: number;
    memory_percent: number;
    memory_used_mb: number;
    memory_total_mb: number;
    thread_count: number;
  };
  redis: {
    queue_depth: number;
    connected: boolean;
  };
  celery: {
    active_tasks: number;
    scheduled_tasks: number;
    workers_online: number;
  };
  captured_at: string;
}
