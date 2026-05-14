// Sitemap (AEM) content dashboard hook.
//
// Backed by GET /api/v1/seo/sitemap/. Returns every public page from
// the AEM page-model JSON exports plus a summary rollup of templates
// and component usage. Static file-backed — refresh is cheap.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { SitemapDashboard } from '../seoTypes';

export function sitemapDashboardKey() {
  return ['seo-sitemap'] as const;
}

export function useSitemapDashboard() {
  return useQuery({
    queryKey: sitemapDashboardKey(),
    queryFn: () => api.get<SitemapDashboard>('/seo/sitemap/'),
    staleTime: 60_000,
  });
}
