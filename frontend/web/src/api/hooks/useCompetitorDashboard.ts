// Competitor gap dashboard hook.
//
// Backed by GET /api/v1/seo/competitor/?domain=... — the first call
// hits SEMrush (40 + ~500/comp units) and politely crawls top pages
// across all rivals, so the *initial* load can take several minutes.
// Results are cached on disk for 7 days so subsequent reloads in the
// same week are instant.
//
// The long-tail wait means we set generous timeouts and disable
// auto-refetch; the user pulls fresh data by clicking "Refresh" which
// will eventually be wired to bust the cache.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { CompetitorDashboard } from '../seoTypes';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

export function competitorDashboardKey(domain: string) {
  return ['seo-competitor', { domain }] as const;
}

export function useCompetitorDashboard(domain: string = DEFAULT_DOMAIN) {
  return useQuery({
    queryKey: competitorDashboardKey(domain),
    queryFn: () =>
      api.get<CompetitorDashboard>('/seo/competitor/', { domain }),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    retry: false,
  });
}
