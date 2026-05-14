// On-demand fetch of a single AEM page's full extracted content.
//
// The list endpoint (/api/v1/seo/sitemap/) keeps responses small by
// shipping only metadata + a short preview per page. Clicking "View"
// on a row mounts the content drawer and triggers this hook, which
// pulls the full body text from /api/v1/seo/sitemap/page/?path=...

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { SitemapPageDetail } from '../seoTypes';

export function sitemapPageKey(aemPath: string | null) {
  return ['seo-sitemap-page', aemPath] as const;
}

export function useSitemapPage(aemPath: string | null) {
  return useQuery({
    queryKey: sitemapPageKey(aemPath),
    queryFn: () =>
      api.get<SitemapPageDetail>('/seo/sitemap/page/', { path: aemPath ?? '' }),
    enabled: Boolean(aemPath),
    staleTime: 5 * 60_000,
  });
}
