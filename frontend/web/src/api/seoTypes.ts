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
