// Adobe Analytics dashboard hook.
//
// Backed by GET /api/v1/seo/adobe/?lookback=7&limit=25. The backend
// authenticates server-to-server against Adobe IMS, caches the
// 24-hour bearer token in memory, then hits Analytics 2.0 for the
// report-suite metadata, available dimensions/metrics counters, top
// pages, daily trend, marketing channels, entry pages, geo, and
// device split — all in one response.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface AdobeTopPageRow {
  page: string;
  page_views: number;
  item_id: string;
}

export interface AdobeReportSuiteInfo {
  rsid: string;
  name: string;
  collection_item_type: string;
}

export interface AdobeDailyPoint {
  date: string; // ISO yyyy-mm-dd
  page_views: number;
  visits: number;
}

export interface AdobeChannelRow {
  channel: string;
  visits: number;
  share_pct: number;
}

export interface AdobeEntryPageRow {
  page: string;
  entries: number;
  bounces: number;
  bounce_rate: number;
  time_on_page_sec: number;
  item_id: string;
}

export interface AdobeGeoRow {
  label: string;
  visits: number;
  share_pct: number;
}

export interface AdobeDeviceRow {
  device_type: string;
  visits: number;
  share_pct: number;
}

export interface AdobeSiteSectionRow {
  section: string;
  page_views: number;
  visits: number;
  share_pct: number;
}

export interface AdobeExitPageRow {
  page: string;
  exits: number;
  exit_rate: number;
  item_id: string;
}

export interface AdobeInternalSearchRow {
  term: string;
  instances: number;
  item_id: string;
}

export interface AdobeHourRow {
  hour: string;
  visits: number;
  share_pct: number;
}

export interface AdobeWeekdayRow {
  weekday: string;
  visits: number;
  share_pct: number;
}

export interface AdobeLangRow {
  language: string;
  visits: number;
  share_pct: number;
}

export interface AdobeBrowserRow {
  browser: string;
  visits: number;
  share_pct: number;
}

export interface AdobeOSRow {
  os_name: string;
  visits: number;
  share_pct: number;
}

export interface AdobeResolutionRow {
  resolution: string;
  visits: number;
  share_pct: number;
}

export interface AdobeReferrerDomainRow {
  domain: string;
  visits: number;
  share_pct: number;
}

export interface AdobeSearchEngineRow {
  engine: string;
  visits: number;
  share_pct: number;
}

export interface AdobeNotFoundRow {
  url: string;
  instances: number;
}

export interface AdobeLeadEventRow {
  hash_value: string;
  occurrences: number;
}

export interface AdobeCatalogueItem {
  id: string;
  name: string;
  description: string;
  owner: string;
  type: string;
  is_calculated: boolean;
}

export interface AdobeVisitorsSummary {
  visitors?: number;
  unique_visitors?: number;
  avg_time_on_site_sec?: number;
  pages_per_visit?: number;
  bounce_rate?: number;
  exits?: number;
}

export type AdobeFreshness = 'live' | 'cached' | 'missing';

export interface AdobeCachedSection {
  ts?: number;
  lookback_days?: number;
  limit?: number;
  size_bytes?: number;
  age_sec?: number | null;
}

export interface AdobeDashboardResponse {
  available: boolean;
  reason?: string;
  error?: string;
  rsid?: string;
  global_company_id?: string;
  lookback_days?: number;
  report_suite?: AdobeReportSuiteInfo | null;
  totals?: {
    total_pages?: number;
    filtered_total_views?: number | null;
    total_views?: number | null;
    col_max?: number | null;
    col_min?: number | null;
  };
  top_pages?: AdobeTopPageRow[];
  daily_trend?: AdobeDailyPoint[];
  channels?: AdobeChannelRow[];
  entry_pages?: AdobeEntryPageRow[];
  countries?: AdobeGeoRow[];
  devices?: AdobeDeviceRow[];
  dimension_count?: number;
  metric_count?: number;
  // Tier 1-3 additions:
  visitors_summary?: AdobeVisitorsSummary;
  site_sections?: AdobeSiteSectionRow[];
  exit_pages?: AdobeExitPageRow[];
  internal_searches?: AdobeInternalSearchRow[];
  page_not_found?: AdobeNotFoundRow[];
  hours?: AdobeHourRow[];
  weekdays?: AdobeWeekdayRow[];
  yoy_daily_trend?: AdobeDailyPoint[];
  regions?: AdobeGeoRow[];
  cities?: AdobeGeoRow[];
  languages?: AdobeLangRow[];
  browsers?: AdobeBrowserRow[];
  operating_systems?: AdobeOSRow[];
  resolutions?: AdobeResolutionRow[];
  channel_detail?: AdobeChannelRow[];
  referrer_domains?: AdobeReferrerDomainRow[];
  search_engines?: AdobeSearchEngineRow[];
  lead_events?: AdobeLeadEventRow[];
  segments?: AdobeCatalogueItem[];
  calculated_metrics?: AdobeCatalogueItem[];
  // Per-section freshness map: section_name -> "live" | "cached" | "missing"
  data_freshness?: Record<string, AdobeFreshness>;
  // When a section is served from cache, age in seconds:
  data_age_sec?: Record<string, number>;
  // Inventory of every cached section on disk for this rsid.
  cached_sections_on_disk?: Record<string, AdobeCachedSection>;
}

export function adobeDashboardKey(lookback: number, limit: number) {
  return ['seo-adobe', { lookback, limit }] as const;
}

export function useAdobeDashboard(lookback = 7, limit = 25) {
  return useQuery({
    queryKey: adobeDashboardKey(lookback, limit),
    queryFn: () =>
      api.get<AdobeDashboardResponse>('/seo/adobe/', { lookback, limit }),
    // Adobe IMS tokens are cached server-side; client cache for 5 min
    // is just to avoid refetching on tab focus storms.
    staleTime: 5 * 60_000,
  });
}

// ── SEO × Adobe cross-source join ────────────────────────────────────

export interface AdobeSeoJoinRow {
  page: string;
  url: string;
  page_views: number;
  visits: number;
  status_code: string;
  title: string;
  word_count: number;
  indexed_status: string;
  from_sitemap: boolean;
  has_any_error: boolean;
  in_crawl: boolean;
  gsc_clicks: number | null;
  gsc_impressions: number | null;
  gsc_position: number | null;
}

export interface AdobeSeoJoinResponse {
  available: boolean;
  reason?: string;
  error?: string;
  lookback_days?: number;
  totals?: {
    rows: number;
    in_crawl: number;
    with_errors: number;
    with_gsc: number;
    high_impression_no_traffic: number;
  };
  rows?: AdobeSeoJoinRow[];
}

export function adobeSeoJoinKey(lookback: number, limit: number) {
  return ['seo-adobe-join', { lookback, limit }] as const;
}

export function useAdobeSeoJoin(lookback = 30, limit = 100) {
  return useQuery({
    queryKey: adobeSeoJoinKey(lookback, limit),
    queryFn: () =>
      api.get<AdobeSeoJoinResponse>('/seo/adobe/seo-join/', {
        lookback,
        limit,
      }),
    staleTime: 5 * 60_000,
  });
}
