// useSessions.ts — TanStack Query hook for the per-website Crawl Sessions list.
//
// Backed by GET /websites/<uuid>/sessions/ (custom action on WebsiteViewSet,
// see backend/apps/crawler/views.py:WebsiteViewSet.list_sessions). Returns the
// latest 50 sessions ordered by -started_at.
//
// Disabled when no site is active so the query never fires with a null id.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { CrawlSessionListItem } from '../types';

export function sessionsQueryKey(websiteId: string | null) {
  // Object form keeps it stable for { website } predicate-style invalidation.
  return ['sessions', { website: websiteId }] as const;
}

export function useSessions(websiteId: string | null) {
  return useQuery({
    queryKey: sessionsQueryKey(websiteId),
    queryFn: () =>
      api.get<CrawlSessionListItem[]>(`/websites/${websiteId}/sessions/`),
    enabled: websiteId !== null,
  });
}
