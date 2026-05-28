/**
 * Per-competitor + per-URL detail hooks.
 *
 * Backed by the Phase 2 endpoints at /api/v1/seo/competitor/<domain>/
 * and /api/v1/seo/competitor/<domain>/pages/<b64url>/. Powers the
 * CompetitorDetailPage and CompetitorPageDetailPage routes that
 * replace the old DeepCrawlPanel "dropdown" view.
 */
import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface SamplePageSummary {
  url: string;
  url_b64: string;
  title: string;
  meta_description: string;
  page_type: string;
  word_count: number;
  has_schema: boolean;
  schema_types: string[];
  response_time_ms: number;
  pagespeed_score: number | null;
  lcp_ms: number | null;
  cls: number | null;
  inp_ms: number | null;
  h1_text: string;
  internal_link_count: number;
  external_link_count: number;
}

export interface CompetitorProfileSummary {
  page_count: number;
  ok_count: number;
  avg_word_count: number;
  median_word_count: number;
  avg_response_ms: number;
  schema_pct: number;
  h1_pct: number;
  page_types: Record<string, number>;
  schema_types: string[];
  has_pricing_page: boolean;
  has_llms_txt: boolean;
  has_pricing_md: boolean;
  ai_citability_score: number;
  cwv_pages_count: number;
  avg_pagespeed_score: number;
  median_lcp_ms: number;
  median_cls: number;
  median_inp_ms: number;
}

export interface CompetitorDetail {
  domain: string;
  is_us: boolean;
  run_id: string;
  run_started_at: string | null;
  sitemap_url_count: number;
  pages_attempted: number;
  pages_ok: number;
  profile_summary: CompetitorProfileSummary;
  sample_pages: SamplePageSummary[];
  sample_count: number;
  error: string;
}

export interface PageHeading {
  level: number;   // 1-6
  text: string;
  idx: number;
}
export interface PageLink {
  anchor: string;
  href: string;
  section: string; // nearest preceding heading text
  kind: string;    // calculator | product_term | blog | … | other
  rel: string;
}
export interface PageImage {
  src: string;
  alt: string;
  width: string;
  height: string;
  section: string;
  loading: string;
}

export interface PageVideo {
  src: string;
  kind: 'native' | 'youtube' | 'vimeo' | 'wistia' | 'other';
  poster: string;
  section: string;
  zone: string;
  width: string;
  height: string;
}

export interface CompetitorPageDetail {
  domain: string;
  url: string;
  url_b64: string;
  title: string;
  meta_description: string;
  h1_texts: string[];
  h2_texts: string[];
  schema_types: string[];
  word_count: number;
  has_schema: boolean;
  page_type: string;
  response_time_ms: number;
  internal_link_count: number;
  external_link_count: number;
  last_modified: string;
  body_text: string;
  pagespeed_score: number | null;
  lcp_ms: number | null;
  cls: number | null;
  inp_ms: number | null;
  // Phase 2A.5 structural mirror — may be empty on legacy GapDeepCrawl
  // rows captured before this field landed.
  headings: PageHeading[];
  internal_links: PageLink[];
  external_links: PageLink[];
  images: PageImage[];
  videos: PageVideo[];
  run_id: string;
  run_started_at: string | null;
}

export function competitorDetailKey(domain: string) {
  return ['seo-competitor-detail', { domain }] as const;
}

export function useCompetitorDetail(domain: string | null) {
  return useQuery({
    queryKey: competitorDetailKey(domain || ''),
    queryFn: () =>
      api.get<CompetitorDetail>(
        `/seo/competitor/${encodeURIComponent(domain || '')}/`,
      ),
    enabled: Boolean(domain),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function competitorPageDetailKey(domain: string, urlB64: string) {
  return ['seo-competitor-page-detail', { domain, urlB64 }] as const;
}

export function useCompetitorPageDetail(
  domain: string | null,
  urlB64: string | null,
) {
  return useQuery({
    queryKey: competitorPageDetailKey(domain || '', urlB64 || ''),
    queryFn: () =>
      api.get<CompetitorPageDetail>(
        `/seo/competitor/${encodeURIComponent(domain || '')}/pages/${urlB64 || ''}/`,
      ),
    enabled: Boolean(domain && urlB64),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

// Snapshot-explicit per-URL detail. Same payload shape as
// CompetitorPageDetail but works for any CrawlSnapshot kind
// (Bajaj / competitor / ad-hoc). Backend adds snapshot_kind +
// snapshot_domain so the page can swap its breadcrumb without a
// second request.
export interface PageDetailResponse extends CompetitorPageDetail {
  snapshot_kind: 'bajaj' | 'competitor' | 'adhoc' | string;
  snapshot_domain: string;
}

export function pageDetailKey(snapshotId: string, urlB64: string) {
  return ['seo-page-detail', { snapshotId, urlB64 }] as const;
}

export function usePageDetail(
  snapshotId: string | null,
  urlB64: string | null,
) {
  return useQuery({
    queryKey: pageDetailKey(snapshotId || '', urlB64 || ''),
    queryFn: () =>
      api.get<PageDetailResponse>(
        `/seo/page/${snapshotId || ''}/${urlB64 || ''}/`,
      ),
    enabled: Boolean(snapshotId && urlB64),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

// Phase 7 — competitor keyword intelligence.
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

export interface ContentKeywordRow {
  keyword: string;
  score: number;
  page_count: number;
  sample_pages: Array<{ url: string; title: string }>;
}

export interface SemrushKeywordsResponse {
  available: boolean;
  domain: string;
  count: number;
  keywords: SemrushKeywordRow[];
  error?: string;
}

export interface ContentKeywordsResponse {
  available: boolean;
  domain: string;
  parent_domain?: string;
  subdomain_count?: number;
  page_count?: number;
  count: number;
  keywords: ContentKeywordRow[];
  error?: string;
}

export function useCompetitorKeywordsSemrush(domain: string | null) {
  return useQuery({
    queryKey: ['competitor-keywords-semrush', { domain }],
    queryFn: () =>
      api.get<SemrushKeywordsResponse>(
        `/seo/competitor/${encodeURIComponent(domain || '')}/keywords/semrush/`,
      ),
    enabled: Boolean(domain),
    staleTime: 30 * 60_000, // Semrush data barely moves; cache 30 min
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useCompetitorKeywordsContent(domain: string | null) {
  return useQuery({
    queryKey: ['competitor-keywords-content', { domain }],
    queryFn: () =>
      api.get<ContentKeywordsResponse>(
        `/seo/competitor/${encodeURIComponent(domain || '')}/keywords/content/`,
      ),
    enabled: Boolean(domain),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}
