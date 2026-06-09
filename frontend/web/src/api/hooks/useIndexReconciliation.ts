import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface SubdomainBucket {
  total: number;
  status_200: number;
  status_404: number;
  status_error: number;
  indexable: number;
  noindex: number;
  canonicalized: number;
}

export interface IndexReconciliation {
  available: boolean;
  error?: string;
  snapshot?: { id: string; started_at: string; status: string; total_pages: number };
  by_subdomain?: Record<string, SubdomainBucket>;
  main_site?: SubdomainBucket;
  gsc?: { pages_with_impressions: number; note: string };
  reconciliation?: {
    gsc_served_proxy: number;
    crawler_main_total: number;
    crawler_main_indexable: number;
    crawler_main_noindex: number;
    crawler_main_canonicalized: number;
    crawler_main_404: number;
    crawler_main_error: number;
  };
}

/**
 * GSC ↔ crawler index-coverage reconciliation for the latest Bajaj crawl.
 * Backed by GET /api/v1/seo/index-reconciliation/.
 */
export function useIndexReconciliation() {
  return useQuery({
    queryKey: ['index-reconciliation'],
    queryFn: () => api.get<IndexReconciliation>('/seo/index-reconciliation/'),
    staleTime: 60_000,
  });
}
