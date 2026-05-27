/**
 * Orchestrator V2 + GEO score hooks — power the Briefings dashboard.
 *
 * Both calls are cheap (~150ms orchestrate, ~60-3000ms GEO depending
 * on deep flag). The Briefings page polls neither — operator-pulled.
 */
import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface ChangeSignal {
  competitor: string;
  kind: string;
  url: string;
  detected_at: string;
}

export interface OrchestrateHeadline {
  total_competitor_changes_7d: number;
  schema_gap_count: number;
  link_kind_gap_count: number;
  structure_gap_count: number;
  cwv_worse_than_competitors: string[];
  biggest_change_signals: ChangeSignal[];
}

export interface OrchestrateResponse {
  generated_at: string;
  elapsed_ms: number;
  our: {
    domain: string;
    ok_page_count: number;
    median_word_count: number;
    has_schema_pct: number;
    avg_pagespeed_score: number | null;
    median_lcp_ms: number | null;
  };
  competitors: Array<{
    domain: string;
    ok_page_count: number;
    recent_changes: Record<string, number>;
  }>;
  diff: {
    page_count_delta: Record<string, number>;
    schema_only_theirs: Record<string, string[]>;
    schema_only_ours: string[];
    link_kind_gaps: Record<string, string[]>;
  };
  adobe?: {
    available: boolean;
    totals?: Record<string, number>;
    top_pages?: Array<{ page: string; page_views: number }>;
    channels?: Array<{ channel: string; visits: number; share_pct: number }>;
    error?: string;
  };
  structure_gaps: Array<{
    source_page_type: string;
    target_kind: string;
    our_pct: number;
    max_their_pct: number;
    domains_with_pattern: number;
  }>;
  headline: OrchestrateHeadline;
}

export function useOrchestrate() {
  return useQuery({
    queryKey: ['orchestrate-v2'],
    queryFn: () => api.get<OrchestrateResponse>('/seo/orchestrate/'),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

// ── GEO score ─────────────────────────────────────────────────────

export interface GeoFactorPageSignals {
  available: boolean;
  reason?: string;
  snapshot_id?: string;
  pages_analysed?: number;
  avg_citation_density?: number;
  avg_eeat_score?: number;
  pages_with_person_schema_pct?: number;
  pages_with_sameas_pct?: number;
}

export interface GeoFactorBotHits {
  available: boolean;
  total_30d?: number;
  by_bot?: Record<string, number>;
  distinct_bots?: number;
}

export interface GeoFactorLlmsTxt {
  present: boolean;
  status_code?: number;
  bytes?: number;
  url_count_approx?: number;
  error?: string;
}

export interface GeoFactorSocial {
  brand: string;
  reddit_count: number;
  quora_count: number;
  reddit_top: Array<{ title: string; link: string; snippet: string }>;
  quora_top: Array<{ title: string; link: string; snippet: string }>;
  error: string;
}

export interface GeoFactorYouTube {
  brand: string;
  channel_url: string;
  video_count: number;
  videos: Array<{ title: string; link: string; snippet?: string }>;
  error: string;
}

export interface GeoFactorWikidata {
  brand: string;
  qid: string;
  label: string;
  description: string;
  sitelinks_count: number;
  has_logo: boolean;
  error: string;
}

export interface GeoFactorBrandMentions {
  available: boolean;
  count_30d?: number;
  tier_breakdown?: Record<string, number>;
  error?: string;
}

export interface GeoScoreResponse {
  brand: string;
  overall_score: number;
  factors: {
    page_signals?: GeoFactorPageSignals;
    ai_bot_hits?: GeoFactorBotHits;
    llms_txt?: GeoFactorLlmsTxt;
    brand_mentions?: GeoFactorBrandMentions;
    social_mentions?: GeoFactorSocial;
    youtube?: GeoFactorYouTube;
    wikidata?: GeoFactorWikidata;
  };
  suggestions: string[];
}

export function useGeoScore(deep = true) {
  return useQuery({
    queryKey: ['geo-score', { deep }],
    queryFn: () =>
      api.get<GeoScoreResponse>(
        `/seo/geo/score/?deep=${deep ? 'true' : 'false'}`,
      ),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

// ── Competitor changes feed ───────────────────────────────────────

export interface ChangeEvent {
  id: number;
  url: string;
  competitor_domain: string;
  kind: string;
  detected_at: string;
  delta: Record<string, unknown>;
}

export interface CompetitorChangesResponse {
  count: number;
  events: ChangeEvent[];
}

export function useCompetitorChanges(params: {
  domain?: string;
  kind?: string;
  limit?: number;
} = {}) {
  const qs = new URLSearchParams();
  if (params.domain) qs.set('domain', params.domain);
  if (params.kind) qs.set('kind', params.kind);
  if (params.limit) qs.set('limit', String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : '';
  return useQuery({
    queryKey: ['competitor-changes', params],
    queryFn: () =>
      api.get<CompetitorChangesResponse>(`/seo/competitor/changes/${suffix}`),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

// ── Layout + Structure gaps (for CustodiansPage panels) ───────────

export interface LayoutZoneRollup {
  link_count: number;
  top_link_kinds: Array<[string, number]>;
  top_link_anchors: Array<[string, number]>;
  heading_count: number;
  top_heading_texts: Array<[string, number]>;
  image_count: number;
  image_alt_pct: number;
}

export interface LayoutResponse {
  our_snapshot_id: string;
  competitor_snapshot_count: number;
  layout: {
    snapshot_id: string;
    zones: Record<string, LayoutZoneRollup>;
  };
  diff: {
    our_snapshot_id: string;
    diffs_by_competitor: Record<
      string,
      Array<{
        zone: string;
        kinds_only_in_competitor: string[];
        their_link_count: number;
        our_link_count: number;
      }>
    >;
  };
}

export function useLayout() {
  return useQuery({
    queryKey: ['custodians-layout'],
    queryFn: () => api.get<LayoutResponse>('/seo/custodians/layout/'),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export interface StructureGapsResponse {
  our_snapshot_id: string;
  competitor_snapshot_count: number;
  min_pct: number;
  gaps: Array<{
    source_page_type: string;
    target_kind: string;
    our_pct: number;
    max_their_pct: number;
    domains_with_pattern: number;
    their_pct_by_domain: Record<string, number>;
  }>;
}

export function useStructureGaps(minPct = 50) {
  return useQuery({
    queryKey: ['custodians-structure-gaps', minPct],
    queryFn: () =>
      api.get<StructureGapsResponse>(
        `/seo/custodians/structure-gaps/?min_pct=${minPct}`,
      ),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}
