// useInsights.ts — TanStack Query hooks for the AI Insights drawer.
//
// Backed by:
//   GET  /sessions/<uuid>/insights/  → cached payload (no Anthropic call
//                                      when the row-cache is warm)
//   POST /sessions/<uuid>/insights/  → force-regenerate (bills Anthropic)
//
// Always returns 200 with the full InsightsResponse shape. When the
// backend reports `available: false`, the drawer renders a "not
// configured" placeholder instead of the live content.
//
// We keep the GET hook lazy (the drawer passes `enabled=true` only after
// it opens). With the row-cache primed by the post-crawl task this is
// effectively free, but `staleTime` of 1 minute still avoids redundant
// network round-trips during open/close cycles.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';
import type { InsightsResponse } from '../types';

export function insightsQueryKey(sessionId: string | null) {
  // Object form keeps it stable for { session } predicate-style invalidation,
  // mirroring the convention in useIssues / useAnalytics.
  return ['insights', { session: sessionId }] as const;
}

export function useInsights(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: insightsQueryKey(sessionId),
    queryFn: () =>
      api.get<InsightsResponse>(`/sessions/${sessionId}/insights/`),
    enabled: sessionId !== null && enabled,
    staleTime: 60_000,
  });
}

/**
 * Mutation: POST /sessions/<id>/insights/ — force-regenerate the cached
 * payload. Used by the "Regenerate" button in AIInsightsDrawer. On
 * success we invalidate the GET query so the drawer re-fetches and shows
 * the fresh result without a manual refresh.
 */
export function useRegenerateInsights() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.post<InsightsResponse>(`/sessions/${sessionId}/insights/`),
    onSuccess: (_data, sessionId) => {
      qc.invalidateQueries({ queryKey: insightsQueryKey(sessionId) });
    },
  });
}
