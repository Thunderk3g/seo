// List every competitor we've Scrapy-walked (Phase G storage).
//
// Backed by GET /api/v1/seo/competitor/crawls/ — one row per
// `target_domain`, latest complete CrawlSnapshot wins. Powers the
// "Crawled Competitors" tab on CompetitorsPage so the operator can
// see live-crawl progress without opening the gap-detection
// pipeline.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface CompetitorCrawlRow {
  domain: string;
  snapshot_id: string;
  started_at: string | null;
  finished_at: string | null;
  pages_attempted: number;
  pages_ok: number;
  pages_in_db: number;
  change_events: number;
  notes: string;
}

export interface CompetitorCrawlsResponse {
  competitors: CompetitorCrawlRow[];
  count: number;
}

export function competitorCrawlsKey() {
  return ['seo-competitor-crawls'] as const;
}

export function useCompetitorCrawls() {
  return useQuery({
    queryKey: competitorCrawlsKey(),
    queryFn: () =>
      api.get<CompetitorCrawlsResponse>('/seo/competitor/crawls/'),
    staleTime: 60_000,
    // Keep the panel fresh during overnight crawl runs without
    // hammering the endpoint. 30s matches the crawler/status poll
    // cadence elsewhere in the app.
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}
