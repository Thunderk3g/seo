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
  word_count: number;
  content_preview: string;
}

export interface SitemapPageDetail {
  public_url: string;
  aem_path: string;
  title: string;
  description: string;
  template_name: string;
  last_modified: string | null;
  word_count: number;
  content: string;
  component_types: string[];
}

export interface CompetitorTopicGap {
  cluster_slug: string;
  competitor_page_count: number;
  our_page_count: number;
  sample_competitor_urls: string[];
  sample_competitor_titles: string[];
  competitors_covering: string[];
}

export interface CompetitorKeywordGap {
  keyword: string;
  competitor_domain: string;
  competitor_position: number;
  competitor_url: string;
  search_volume: number;
  competitor_traffic_pct: number;
  score: number;
}

export interface CompetitorHygieneDelta {
  cluster_slug: string;
  our_avg_title_length: number;
  competitor_avg_title_length: number;
  our_avg_description_length: number;
  competitor_avg_description_length: number;
  our_h1_pct: number;
  competitor_h1_pct: number;
  our_schema_pct: number;
  competitor_schema_pct: number;
  competitor_pages_sampled: number;
  our_pages_sampled: number;
}

export interface CompetitorVolumeDelta {
  cluster_slug: string;
  our_page_count: number;
  competitor_page_count: number;
  our_avg_word_count: number;
  competitor_avg_word_count: number;
  our_total_words: number;
  competitor_total_words: number;
}

// ── Phase 2A — new dimensions ───────────────────────────────────

export interface CompetitorProductCoverage {
  product_slug: string;
  our_page_count: number;
  competitor_counts: Record<string, number>;
  sample_competitor_urls: string[];
}

export interface CompetitorStructureDelta {
  cluster_slug: string;
  our_avg_h2: number;
  competitor_avg_h2: number;
  our_avg_h3: number;
  competitor_avg_h3: number;
  our_avg_internal_links: number;
  competitor_avg_internal_links: number;
  our_avg_external_links: number;
  competitor_avg_external_links: number;
  our_avg_image_alt_pct: number;
  competitor_avg_image_alt_pct: number;
  our_avg_cta_count: number;
  competitor_avg_cta_count: number;
  our_schema_type_count: number;
  competitor_schema_type_count: number;
  our_pages_sampled: number;
  competitor_pages_sampled: number;
}

export interface CompetitorLoadingTimeDelta {
  cluster_slug: string;
  our_median_ms: number;
  competitor_median_ms: number;
  our_p90_ms: number;
  competitor_p90_ms: number;
  our_pages_sampled: number;
  competitor_pages_sampled: number;
}

export interface CompetitorContentFitDelta {
  keyword: string;
  competitor_domain: string;
  competitor_url: string;
  competitor_position: number;
  search_volume: number;
  competitor_word_count: number;
  competitor_keyword_occurrences: number;
  competitor_keyword_density: number;
  fit_verdict: 'strong' | 'moderate' | 'thin' | 'none';
}

export interface CompetitorSummary {
  domain: string;
  competition_level: number;
  common_keywords: number;
  top_pages_pulled: number;
  keywords_pulled: number;
  pages_crawled_ok: number;
  pages_crawl_attempted: number;
  total_url_count: number;          // Phase 2A — sitemap.xml-derived
}

export interface CompetitorDashboard {
  available: boolean;
  error?: string;
  domain?: string;
  summary?: {
    competitors_analysed: number;
    topic_gaps_found: number;
    keyword_gaps_found: number;
    hygiene_deltas_found: number;
    content_volume_deltas_found: number;
    competitor_pages_crawled_ok: number;
    competitor_pages_crawl_attempted: number;
    // Phase 2A
    our_pages_crawled_ok?: number;
    our_pages_crawl_attempted?: number;
    our_total_url_count?: number;
    product_coverage_rows?: number;
    structure_deltas_found?: number;
    loading_time_deltas_found?: number;
    content_fit_items?: number;
  };
  competitors?: CompetitorSummary[];
  topic_gaps?: CompetitorTopicGap[];
  keyword_gaps?: CompetitorKeywordGap[];
  hygiene_deltas?: CompetitorHygieneDelta[];
  content_volume_deltas?: CompetitorVolumeDelta[];
  // Phase 2A
  product_coverage?: CompetitorProductCoverage[];
  structure_deltas?: CompetitorStructureDelta[];
  loading_time_deltas?: CompetitorLoadingTimeDelta[];
  content_fit_deltas?: CompetitorContentFitDelta[];
  total_url_count_by_competitor?: Record<string, number>;
  our_total_url_count?: number;
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

// ── Competitor Gap Detection (Phase 2 — 7 detection agents) ────────

export type DetectionAgentName =
  | 'ai_visibility'
  | 'serp_visibility'
  | 'competitor_discovery'
  | 'technical_audit'
  | 'architecture_audit'
  | 'content_extractability'
  | 'product_commercial';

export interface DetectionFinding {
  id: string;
  agent: DetectionAgentName | string;
  severity: SEOFindingSeverity;
  category: string;
  title: string;
  description: string;
  recommendation: string;
  evidence_refs: string[];
  impact: string;
  effort: string;
  priority: number;
}

export interface AgentStatus {
  status: 'skipped' | 'crashed';
  reason: string;
}

export interface CompetitorGapResponse {
  available: boolean;
  domain: string;
  run_id?: string;
  finished_at?: string | null;
  findings_by_agent?: Record<string, DetectionFinding[]>;
  agent_status?: Record<string, AgentStatus>;
}

// ── Conversational chat ─────────────────────────────────────────────

export type ChatRole = 'user' | 'assistant' | 'tool';

export interface ChatToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result: unknown;
}

export interface ChatCard {
  card_type: string;
  payload: Record<string, unknown>;
}

export interface ChatMessage {
  role: ChatRole;
  content: string;
  toolCalls?: ChatToolCall[];
  cards?: ChatCard[];
  // Set on the assistant message once a stream finishes.
  tokensIn?: number;
  tokensOut?: number;
  costUsd?: number;
  timestamp: number;
}
