/**
 * ContentWriter — LLM-driven rewrites grounded in real evidence.
 *
 * Backed by /api/v1/seo/content-writer/. Pulls the list of crawled
 * URLs the writer can target, generates a rewrite proposal, and lists
 * recent proposals so the operator can revisit them.
 *
 * The proposal's source-of-truth is the deterministic critic verdict:
 * every generated string has a ``source_ref`` and a backend pass drops
 * anything that doesn't resolve into the evidence dict.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';

// ── V2 — SERP-discovery-driven page revamp ─────────────────────────
// Lives at /content-writer-v2 and talks to /seo/content-writer/v2/*.
// Independent of the legacy DB-roster flow above — the response shape
// is different (full stage-by-stage payload) and we intentionally do
// NOT reuse ContentRewriteProposal here.

export interface CWV2SerpCandidate {
  position: number;
  url: string;
  domain: string;
  title: string;
  snippet: string;
  found_via_query?: string;
  page_type?: string; // product | comparison | calculator | blog | other
  source?: string; // serp | web_search | custom
  type_match?: boolean; // matches OUR page type
}

export interface CWV2BajajPresence {
  found: boolean;
  best_position: number | null;
  query: string;
  url: string;
  source: string;
}

export interface CWV2SerpStage {
  our_url: string;
  primary_query: string;
  candidate_queries: string[];
  all_queries?: string[];
  queries_run?: string[];
  people_also_ask: string[];
  featured_snippet: unknown;
  ai_overview: unknown;
  competitors: CWV2SerpCandidate[];
  substitution_pool?: CWV2SerpCandidate[];
  blocked: CWV2SerpCandidate[];
  bajaj_presence?: CWV2BajajPresence;
  serp_engine: string;
  serp_error: string;
  llm_model: string;
  llm_cost_usd: number;
  web_search_used?: boolean;
  our_page_type?: string; // type we matched competitors against
  notes: string[];
}

export interface CWV2HeadingNode {
  level: number;
  text: string;
  children: CWV2HeadingNode[];
}

export interface CWV2ClusterSection {
  section_id?: number;
  name: string;
  rationale?: string;
  topics_covered?: string[];
  heading_texts?: string[];
  internal_links?: { anchor: string; href: string; kind?: string }[];
  image_count?: number;
  word_count?: number;
}

export interface CWV2PageStructure {
  url: string;
  title: string;
  word_count: number;
  domain?: string;
  heading_counts: { h1: number; h2: number; h3: number; h4_plus: number };
  heading_outline: CWV2HeadingNode[];
  internal_link_count: number;
  unique_internal_targets: number;
  internal_link_density_per_1k_words?: number;
  internal_links: { anchor: string; href: string; section?: string }[];
  image_count: number;
  image_alt_coverage_pct: number;
  images: { src: string; alt: string; section?: string }[];
  external_link_count?: number;
  unique_external_domains?: number;
  trusted_schema_present?: string[];
  clusters: CWV2ClusterSection[];
}

export interface CWV2PageAnalysis {
  url: string;
  title: string;
  title_length: number;
  meta_description: string;
  meta_description_length: number;
  word_count: number;
  reading_time_minutes: number;
  content_size_bytes: number;
  h1_count: number;
  h2_count: number;
  h3_count: number;
  h4_plus_count: number;
  heading_outline_text: string[];
  internal_link_count: number;
  internal_link_density_per_1k_words: number;
  unique_internal_targets: number;
  external_link_count: number;
  unique_external_domains: number;
  image_count: number;
  image_alt_coverage_pct: number;
  video_count: number;
  jsonld_types: string[];
  trusted_schema_present: string[];
  has_faq_schema: boolean;
  has_organization_schema: boolean;
  has_breadcrumb_schema: boolean;
  detected_faq_questions: string[];
  faq_question_count: number;
  cta_count: number;
  detected_ctas: string[];
}

export interface CWV2DimensionGap {
  dimension: string;
  our_value: number;
  competitor_median: number;
  competitor_max: number;
  delta_vs_median: number;
  priority: number;
  headline: string;
  per_competitor: { competitor: string; value: number }[];
}

export interface CWV2SectionGap {
  competitor_domain: string;
  competitor_url: string;
  section_title: string;
  summary: string;
  heading_path: string[];
  priority: number;
}

export interface CWV2GapReport {
  our_url: string;
  competitor_count: number;
  top_priority_actions: string[];
  dimensions: CWV2DimensionGap[];
  section_gaps: CWV2SectionGap[];
  competitor_summary: {
    domain: string;
    url: string;
    title: string;
    word_count: number;
    h2_count: number;
    internal_links: number;
    images: number;
    faq_questions: number;
    schema_types: string[];
  }[];
}

export interface CWV2SeoIssue {
  code: string;
  severity: 'critical' | 'warning' | 'notice';
  dimension: string;
  message: string;
  current_value?: string;
  target?: string;
}

export interface CWV2SeoOverlay {
  issues: CWV2SeoIssue[];
  counts: { critical: number; warning: number; notice: number };
  score: number;
}

export interface CWV2Revamp {
  rewrite_strategy?: string;
  target_word_count?: number;
  title?: { text: string; char_count: number; rationale?: string };
  meta_description?: { text: string; char_count: number; rationale?: string };
  h1?: { text: string; rationale?: string };
  outline?: {
    level: number;
    heading: string;
    estimated_words?: number;
    rationale?: string;
    closes_gaps?: string[];
    sub_headings?: { level: number; heading: string }[];
  }[];
  body_html?: string;
  faqs?: { question: string; answer: string; source: string }[];
  internal_links_plan?: {
    anchor: string;
    target_url: string;
    section: string;
    rationale?: string;
  }[];
  json_ld_blocks?: { type: string; json_ld: unknown }[];
  tech_recommendations?: string[];
}

export interface CWV2RunPayload {
  run_id: string;
  status: 'pending' | 'running' | 'complete' | 'failed';
  our_url: string;
  operator_prompt: string;
  max_competitors?: number;
  llm_enabled?: boolean;
  stages: {
    serp_discovery: CWV2SerpStage;
    our_page_analysis: CWV2PageAnalysis;
    competitor_analyses: { domain: string; analysis: CWV2PageAnalysis }[];
    our_sections: { sections: { title: string; summary: string }[] };
    competitor_sections: Record<
      string,
      { sections: { title: string; summary: string }[] }
    >;
    our_structure?: CWV2PageStructure;
    competitor_structures?: Record<string, CWV2PageStructure>;
    gap_report: CWV2GapReport;
    seo_overlay: CWV2SeoOverlay;
    revamp: CWV2Revamp;
    revamp_error?: string;
  };
  telemetry: {
    wall_time_seconds: number;
    model_used: string;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
    writer_cost_usd?: number;
    budget_cap_usd?: number;
    degraded?: boolean;
    writer_latency_seconds: number;
  };
  warnings: string[];
  created_at: string;
  finished_at: string;
}

export interface CWV2RunSummary {
  run_id: string;
  our_url: string;
  operator_prompt: string;
  status: string;
  model_used: string;
  cost_usd: number;
  competitor_count: number;
  created_at: string;
  finished_at: string;
}

export interface StartCWV2Input {
  our_url: string;
  operator_prompt?: string;
  max_competitors?: number;
  custom_urls?: string[]; // operator-supplied exact competitor URLs
}

const V2_LIST_KEY = ['content-writer-v2', 'runs'] as const;

export function useCWV2Start() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StartCWV2Input) =>
      api.post<CWV2RunPayload>('/seo/content-writer/v2/start/', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: V2_LIST_KEY });
    },
  });
}

export function useCWV2Runs() {
  return useQuery({
    queryKey: V2_LIST_KEY,
    queryFn: () =>
      api.get<{ runs: CWV2RunSummary[] }>('/seo/content-writer/v2/runs/'),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useCWV2Run(id: string | null) {
  return useQuery({
    queryKey: ['content-writer-v2', 'run', id],
    queryFn: () =>
      api.get<CWV2RunPayload>(`/seo/content-writer/v2/runs/${id}/`),
    enabled: Boolean(id),
    // The run executes in a background thread on the server. Poll while it is
    // still working (running/pending) and stop the moment it reaches a
    // terminal state, so the draft appears automatically when it finishes.
    // react-query v5 passes the query object to the refetchInterval callback.
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'running' || s === 'pending' ? 3500 : false;
    },
    refetchOnWindowFocus: false,
    retry: false,
  });
}
