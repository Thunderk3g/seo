// useActivity.ts — TanStack Query hook for the Dashboard activity feed.
//
// Polled every 1.5s while the session is running. Returns merged events
// from /sessions/<uuid>/activity/?since=<iso>. The backend already merges
// persisted CrawlEvent rows + synthesized per-URL Page events.
//
// We do NOT use useInfiniteQuery here — the backend caps the response at
// `limit` rows and we keep a 14-row rolling buffer client-side instead. The
// `since` cursor is the timestamp of the newest entry we've seen.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { CrawlEvent, SessionStatus } from '../types';

export function activityQueryKey(sessionId: string | null) {
  return ['activity', { session: sessionId }] as const;
}

export interface UseActivityArgs {
  sessionId: string | null;
  status?: SessionStatus | null;
  limit?: number;
}

export function useActivity({ sessionId, status, limit = 50 }: UseActivityArgs) {
  return useQuery({
    queryKey: activityQueryKey(sessionId),
    queryFn: () =>
      api.get<CrawlEvent[]>(`/sessions/${sessionId}/activity/`, {
        limit,
      }),
    enabled: sessionId !== null,
    // Live poll only while the crawl is running; once terminal, the feed is
    // stable and re-fetching wastes cycles.
    refetchInterval: status === 'running' || status === 'pending' ? 1500 : false,
  });
}
