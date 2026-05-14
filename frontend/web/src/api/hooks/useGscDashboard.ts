// GSC source-data dashboard hook.
//
// Backed by GET /api/v1/seo/gsc/?limit=200. Returns the full query and
// page tables plus the daily clicks/impressions series — the Overview
// page bundles a slimmer subset, but the GSC page renders the lot.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { GSCDashboard } from '../seoTypes';

export function gscDashboardKey(limit: number) {
  return ['seo-gsc', { limit }] as const;
}

export function useGscDashboard(limit = 200) {
  return useQuery({
    queryKey: gscDashboardKey(limit),
    queryFn: () => api.get<GSCDashboard>('/seo/gsc/', { limit }),
    staleTime: 60_000,
  });
}
