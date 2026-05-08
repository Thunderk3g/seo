// useAnalytics.ts — TanStack Query hook for the per-session analytics charts.
//
// Backed by GET /sessions/<uuid>/analytics/ which returns a single JSON
// payload with all four chart datasets (status / depth / response-time /
// content-type) plus `total_pages`. See AnalyticsService.get_chart_data in
// backend/apps/crawl_sessions/services/analytics_service.py.
//
// Disabled until a sessionId is known so the query never fires with null.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { AnalyticsCharts } from '../types';

export function analyticsQueryKey(sessionId: string | null) {
  // Object form keeps it stable for { session } predicate-style invalidation.
  return ['analytics', { session: sessionId }] as const;
}

export function useAnalytics(sessionId: string | null) {
  return useQuery({
    queryKey: analyticsQueryKey(sessionId),
    queryFn: () =>
      api.get<AnalyticsCharts>(`/sessions/${sessionId}/analytics/`),
    enabled: sessionId !== null,
  });
}
