// Adobe Analytics dashboard hook.
//
// Backed by GET /api/v1/seo/adobe/?lookback=7&limit=25. The backend
// authenticates server-to-server against Adobe IMS, caches the
// 24-hour bearer token in memory, then hits Analytics 2.0 for the
// report-suite metadata, available dimensions/metrics counters, and
// the trailing-window top-pages report.
//
// Returns `{ available: false, reason: 'not_configured' }` when the
// ADOBE_* env vars are missing — AdobePage renders the onboarding
// empty state in that case.

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
  dimension_count?: number;
  metric_count?: number;
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
