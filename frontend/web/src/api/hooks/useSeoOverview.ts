// TanStack Query hook that powers the GSC-style Overview page.
//
// Backed by GET /api/v1/seo/overview/?domain=<domain>. The endpoint
// bundles the latest grading run, the GSC rollup, and the crawler
// rollup so the dashboard paints from one query.
//
// Refetch interval is generous (60 s) because the underlying data
// (CSV pulls, completed grades) doesn't tick in real time.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { SeoOverview } from '../seoTypes';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

export function seoOverviewQueryKey(domain: string) {
  return ['seo-overview', { domain }] as const;
}

export function useSeoOverview(domain: string = DEFAULT_DOMAIN) {
  return useQuery({
    queryKey: seoOverviewQueryKey(domain),
    queryFn: () => api.get<SeoOverview>('/seo/overview/', { domain }),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
