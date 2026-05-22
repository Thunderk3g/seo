// Brand Mentions dashboard hook.
//
// Backed by GET /api/v1/seo/brand-mentions/. The backend aggregates
// third-party mentions of Bajaj from RSS feeds + SerpAPI daily +
// (future) Common Crawl, sentiment-scores them via Groq, and returns
// totals, a 90-day trend, tier/variant breakdowns, top domains, and
// the recent mentions feed.
//
// The same endpoint accepts filters via query params (sentiment, tier,
// variant, q) and pagination (page, page_size). Filters only narrow
// the `mentions` feed — the aggregates stay site-wide so the KPI
// strip is always meaningful.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';

export interface BrandMentionTotals {
  total: number;
  last_week: number;
  pct_positive: number;
  pct_negative: number;
  pct_old_brand: number;
  pct_ai_visible_sources: number;
  by_sentiment: Record<string, number>;
}

export interface SentimentTrendPoint {
  date: string;
  positive: number;
  neutral: number;
  negative: number;
  unscored: number;
}

export interface BrandMention {
  id: string;
  source_url: string;
  source_domain: string;
  source_title: string;
  snippet: string;
  body_excerpt: string;
  brand_variant: 'new' | 'old' | 'parent' | 'ambiguous';
  source_tier: string;
  sentiment: 'positive' | 'neutral' | 'negative' | 'unscored';
  sentiment_confidence: number;
  is_linked: boolean;
  anchor_texts: string[];
  author: string;
  publisher: string;
  co_mentioned_brands: string[];
  language: string;
  rating_value: number | null;
  rating_max: number | null;
  page_fetched: boolean;
  discovered_via: string;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface BrandMentionsResponse {
  available: boolean;
  empty: boolean;
  message?: string;
  totals?: BrandMentionTotals;
  sentiment_trend?: SentimentTrendPoint[];
  tier_breakdown?: { tier: string; count: number }[];
  variant_breakdown?: { variant: string; count: number }[];
  top_domains?: { source_domain: string; count: number }[];
  mentions?: BrandMention[];
  feed_total?: number;
  page?: number;
  page_size?: number;
}

export interface BrandMentionFilters {
  sentiment?: string;
  tier?: string;
  variant?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

export function brandMentionsKey(filters: BrandMentionFilters) {
  return ['seo-brand-mentions', filters] as const;
}

export function useBrandMentions(filters: BrandMentionFilters = {}) {
  return useQuery({
    queryKey: brandMentionsKey(filters),
    queryFn: () => {
      const params = new URLSearchParams();
      if (filters.sentiment) params.append('sentiment', filters.sentiment);
      if (filters.tier) params.append('tier', filters.tier);
      if (filters.variant) params.append('variant', filters.variant);
      if (filters.q) params.append('q', filters.q);
      if (filters.page !== undefined) params.append('page', String(filters.page));
      if (filters.page_size !== undefined)
        params.append('page_size', String(filters.page_size));
      const qs = params.toString();
      return api.get<BrandMentionsResponse>(
        `/seo/brand-mentions/${qs ? '?' + qs : ''}`,
      );
    },
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/** "Refresh now" button — triggers a synchronous pull on the backend. */
export function useRefreshBrandMentions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{
        ok: boolean;
        total_new: number;
        total_updated: number;
        total_fetched: number;
        sentiment_scored: number;
        sources: Array<{
          source: string;
          fetched: number;
          new: number;
          updated: number;
          error: string;
        }>;
      }>('/seo/brand-mentions/refresh/', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['seo-brand-mentions'] });
    },
  });
}
