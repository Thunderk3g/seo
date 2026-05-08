// useLinks.ts — TanStack Query hook for the Visualizations Network-graph tab.
//
// Backed by GET /sessions/<uuid>/links/ which returns a flat list of `Link`
// rows (LinkSerializer). The backend already caps the result set at 500 rows
// (see backend/apps/crawler/views.py::CrawlSessionViewSet.links).
//
// Note: this endpoint does NOT use DRF pagination — it returns the raw array.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { Link } from '../types';

export function linksQueryKey(sessionId: string | null) {
  return ['links', { session: sessionId }] as const;
}

export function useLinks(sessionId: string | null) {
  return useQuery({
    queryKey: linksQueryKey(sessionId),
    queryFn: () => api.get<Link[]>(`/sessions/${sessionId}/links/`),
    enabled: sessionId !== null,
  });
}
