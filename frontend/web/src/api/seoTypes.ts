// TypeScript types for the seo_ai backend (Phase 0 implementation).
//
// Matches the DRF serializers in `backend/apps/seo_ai/serializers.py`
// and the dashboard payload assembled in `backend/apps/seo_ai/overview.py`.
//
// Kept in a separate file from `api/types.ts` so the legacy crawler
// types don't grow unbounded while we iterate on the SEO AI layer.

export type SEORunStatus =
  | 'pending'
  | 'running'
  | 'critic'
  | 'complete'
  | 'degraded'
  | 'failed';

export type SEOFindingSeverity = 'critical' | 'warning' | 'notice';

export interface SEORunSubScores {
  technical: number;
  core_web_vitals: number;
  internal_linking: number;
  structured_data: number;
  indexability: number;
  serp_ctr: number;
  content: number;
  backlinks: number;
}

export interface SEORun {
  id: string;
  domain: string;
  triggered_by: string;
  status: SEORunStatus;
  started_at: string;
  finished_at: string | null;
  overall_score: number | null;
  sub_scores: Partial<SEORunSubScores> | Record<string, number>;
  weights: Record<string, number>;
  sources_snapshot: Record<string, unknown>;
  model_versions: {
    provider?: string;
    model?: string;
    narrative?: {
      executive_summary?: string;
      top_action_this_week?: string;
    };
    critic_verdict?: Record<string, unknown>;
  };
  total_cost_usd: number;
  error: string;
  findings_count: number;
}

export interface SEORunFinding {
  id: string;
  agent: string;            // technical | keyword | content | competitor
  severity: SEOFindingSeverity;
  category: string;
  title: string;
  description: string;
  recommendation: string;
  evidence_refs: string[];
  impact: 'high' | 'medium' | 'low';
  effort: 'high' | 'medium' | 'low';
  priority: number;         // 1..100
}

export interface SEORunMessage {
  id: string;
  step_index: number;
  from_agent: string;
  to_agent: string;
  role: 'system' | 'user' | 'assistant' | 'tool' | 'critic';
  content: Record<string, unknown>;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  created_at: string;
}

// ─────────────────────────────────────────────────────────────────────
// Overview payload — `/api/v1/seo/overview/?domain=...`
// ─────────────────────────────────────────────────────────────────────

export interface GSCQueryRow {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface GSCPageRow {
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface GSCDailyRow {
  date: string;          // YYYY-MM-DD
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface GSCPayload {
  available: boolean;
  error?: string;
  totals?: {
    queries: number;
    pages: number;
    clicks: number;
    impressions: number;
    avg_ctr: number;
    avg_position: number;
  };
  top_queries?: GSCQueryRow[];
  top_pages?: GSCPageRow[];
  underperforming_queries?: GSCQueryRow[];
  daily_series?: GSCDailyRow[];
}

export interface CrawlerPayload {
  available: boolean;
  error?: string;
  totals?: {
    pages: number;
    ok: number;
    errors: number;
    redirects: number;
    '404': number;
    '5xx': number;
    orphan: number;
    thin_content: number;
  };
  median_response_ms?: number;
  status_breakdown?: Record<string, number>;
}

export interface SeoOverviewLatestRun {
  id: string;
  status: SEORunStatus;
  overall_score: number | null;
  sub_scores: Partial<SEORunSubScores>;
  started_at: string | null;
  finished_at: string | null;
  executive_summary: string;
  top_action: string;
  top_findings: Array<
    Pick<
      SEORunFinding,
      'id' | 'agent' | 'severity' | 'title' | 'category' | 'recommendation' | 'priority'
    >
  >;
  total_cost_usd: number;
}

export interface SeoOverview {
  domain: string;
  latest_run: SeoOverviewLatestRun | null;
  gsc: GSCPayload;
  crawler: CrawlerPayload;
}

// ─────────────────────────────────────────────────────────────────────
// Source-data dashboards
// ─────────────────────────────────────────────────────────────────────

export interface GSCDashboard {
  available: boolean;
  error?: string;
  snapshot_path?: string;
  totals?: {
    queries: number;
    pages: number;
    clicks: number;
    impressions: number;
    avg_ctr: number;
    avg_position: number;
  };
  top_queries?: GSCQueryRow[];
  top_pages?: GSCPageRow[];
  underperforming_queries?: GSCQueryRow[];
  high_impression_low_click_queries?: GSCQueryRow[];
  daily_series?: GSCDailyRow[];
}

export interface SemrushOverviewRow {
  domain: string;
  database: string;
  rank: number;
  organic_keywords: number;
  organic_traffic: number;
  organic_cost: number;
  adwords_keywords: number;
  adwords_traffic: number;
  adwords_cost: number;
}

export interface SemrushKeywordRow {
  keyword: string;
  position: number;
  previous_position: number;
  search_volume: number;
  cpc: number;
  competition: number;
  traffic_pct: number;
  url: string;
}

export interface SemrushDashboard {
  available: boolean;
  error?: string;
  domain?: string;
  database?: string;
  overview?: SemrushOverviewRow;
  keywords?: SemrushKeywordRow[];
}

export interface SitemapPageRow {
  public_url: string;
  aem_path: string;
  title: string;
  description: string;
  template_name: string;
  last_modified: string | null;
  component_count: number;
  title_length: number;
  description_length: number;
}

export interface SitemapDashboard {
  available: boolean;
  error?: string;
  snapshot_path?: string;
  totals?: {
    pages: number;
    with_description: number;
    without_description: number;
    short_title: number;
    long_title: number;
    short_desc: number;
    long_desc: number;
  };
  distinct_templates?: string[];
  component_usage?: Record<string, number>;
  most_recent_modification?: string | null;
  least_recent_modification?: string | null;
  pages?: SitemapPageRow[];
}
