// Meta Ads (Apify-sourced) hook.
//
// Pulls competitor ads via /api/v1/seo/meta-ads/?competitor=<name>.
// The backend adapter caches per-competitor responses on disk for 24h
// to avoid burning Apify credit on every page render.
//
// Used by:
//   - CompetitorDetailPage (single competitor — pass one name)
//   - CompetitorsPage overview (aggregate — pass multiple names)

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface MetaAdCard {
  title: string;
  body: string;
  link_url: string;
  cta_text: string;
  image_url: string;
  video_url: string;
  // Poster frame for video ads (FB returns video_preview_image_url),
  // and a watermarked-thumbnail fallback for everything else. Without
  // this, video-ad cards render as "No image" tiles since image_url is
  // empty for videos.
  thumbnail_url: string;
}

export interface MetaAd {
  ad_archive_id: string;
  page_name: string;
  page_id: string;
  page_profile_url: string;
  page_profile_picture_url: string;
  start_date_iso: string;
  end_date_iso: string;
  is_active: boolean;
  publisher_platforms: string[];
  languages: string[];
  categories: string[];
  cta_text: string;
  primary_link_url: string;
  cards: MetaAdCard[];
  raw_caption: string;
}

export interface CompetitorAdsSummary {
  competitor: string;
  total_ads: number;
  active_ads: number;
  page_name: string;
  page_id: string;
  page_profile_picture_url: string;
  top_landing_domains: { domain: string; count: number }[];
  top_landing_paths: { path: string; count: number }[];
  top_ctas: { cta: string; count: number }[];
  publisher_platforms: { platform: string; count: number }[];
  common_themes: { theme: string; count: number }[];
  new_ads_last_7d: number;
  ads: MetaAd[];
  error: string;
}

export interface MetaAdsDashboardResponse {
  available: boolean;
  reason?: string;
  error?: string;
  country?: string;
  refreshed_at?: string;
  cost_estimate_usd?: number;
  total_ads_fetched?: number;
  competitors_processed?: number;
  competitors?: CompetitorAdsSummary[];
}

export function metaAdsKey(
  competitors: string[],
  country: string,
  count: number,
  includeOurs: boolean,
) {
  return [
    'seo-meta-ads',
    {
      competitors: competitors.join('|'),
      country,
      count,
      includeOurs,
    },
  ] as const;
}

/**
 * Fetch Meta Ad Library data for one or more competitors.
 *
 * `competitors` accepts an array of free-text search terms — usually
 * the competitor domain (e.g. `"hdfclife.com"`) or company name
 * (`"HDFC Life Insurance"`). Apify's underlying search handles both.
 *
 * Pass an empty array to fall back to the backend's default competitor
 * roster (set via APIFY_META_ADS_COMPETITORS env).
 *
 * `includeOurs` (default false) controls whether the backend prepends
 * Bajaj's own brand to the request. Competitor-specific sections must
 * leave this false so they don't render Bajaj's ads under a
 * competitor's banner — the dedicated /meta-ads page is the
 * canonical surface for our own ads.
 */
export function useMetaAds(
  competitors: string[],
  opts: {
    country?: string;
    count?: number;
    enabled?: boolean;
    includeOurs?: boolean;
  } = {},
) {
  const country = opts.country ?? 'IN';
  const count = opts.count ?? 25;
  const enabled = opts.enabled ?? true;
  const includeOurs = opts.includeOurs ?? false;
  return useQuery({
    queryKey: metaAdsKey(competitors, country, count, includeOurs),
    queryFn: () => {
      const params = new URLSearchParams();
      for (const c of competitors) {
        if (c.trim()) params.append('competitor', c);
      }
      params.append('country', country);
      params.append('count', String(count));
      params.append('include_ours', includeOurs ? 'true' : 'false');
      return api.get<MetaAdsDashboardResponse>(
        `/seo/meta-ads/?${params.toString()}`,
      );
    },
    enabled,
    staleTime: 30 * 60_000,
    refetchOnWindowFocus: false,
  });
}
