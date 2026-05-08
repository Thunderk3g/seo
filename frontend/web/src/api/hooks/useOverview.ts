// useOverview.ts — TanStack Query hook for the Dashboard snapshot.
//
// Backed by GET /sessions/<uuid>/overview/ which returns a single JSON
// payload with the KPI strip, the SEO Health gauge data, and the
// system-metrics card. See OverviewService.get_overview in
// backend/apps/crawl_sessions/services/overview_service.py.
//
// Disabled until a sessionId is known so the query never fires with
// null. While the session is running we re-poll every 2s so the KPI
// strip and the gauge stay live alongside the activity feed; once the
// session is in a terminal state we stop polling.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { OverviewSnapshot } from '../types';

export function overviewQueryKey(sessionId: string | null) {
  // Object form keeps it stable for { session } predicate-style invalidation,
  // mirroring useIssues / useAnalytics / useSessions conventions.
  return ['overview', { session: sessionId }] as const;
}

export function useOverview(sessionId: string | null) {
  return useQuery({
    queryKey: overviewQueryKey(sessionId),
    queryFn: () =>
      api.get<OverviewSnapshot>(`/sessions/${sessionId}/overview/`),
    enabled: sessionId !== null,
    // Poll every 2s while the crawl is running so the KPI strip and
    // health gauge stay in lockstep with the activity feed; otherwise
    // the data is stable and re-fetching wastes cycles.
    refetchInterval: (q) =>
      q.state.data?.session_status === 'running' ? 2000 : false,
  });
}
