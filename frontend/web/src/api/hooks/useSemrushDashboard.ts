// SEMrush keywords dashboard hook.
//
// Backed by GET /api/v1/seo/semrush/?domain=...&limit=100. Each row
// costs 10 SEMrush API units server-side; the response is cached on
// disk for 24h so re-renders are free. Don't bump limit casually.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { SemrushDashboard } from '../seoTypes';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

export function semrushDashboardKey(domain: string, limit: number) {
  return ['seo-semrush', { domain, limit }] as const;
}

export function useSemrushDashboard(
  domain: string = DEFAULT_DOMAIN,
  limit = 100,
) {
  return useQuery({
    queryKey: semrushDashboardKey(domain, limit),
    queryFn: () =>
      api.get<SemrushDashboard>('/seo/semrush/', { domain, limit }),
    staleTime: 5 * 60_000,
  });
}
