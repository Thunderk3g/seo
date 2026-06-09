import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface ContentSection {
  level: number;
  tag: string;
  heading: string;
  words: number;
  text: string;
}

export interface ContentPageBlock {
  key: string;
  name: string;
  url: string;
  words: number;
  // Per-page structure stats (mini report) — present on live-crawl data.
  h1?: number;
  h2?: number;
  h3?: number;
  links_internal?: number | null;
  links_external?: number | null;
  images?: number | null;
  sections: ContentSection[];
}

export interface ContentCluster {
  id: string;
  name: string;
  intro: string;
  page_count: number;
  section_count: number;
  word_count: number;
  pages: ContentPageBlock[];
}

export interface ContentClustersResponse {
  available: boolean;
  brand?: string;
  note?: string;
  // Snapshot serving the clusters — drives /crawler/pages/<id>/<b64> links.
  snapshot_id?: string;
  snapshot_kind?: string;
  clusters?: ContentCluster[];
  error?: string;
}

/**
 * In-house cross-page content segregation for the Content page.
 * Backed by GET /api/v1/seo/content/clusters/ — the Claude-Code segmenter
 * output (no embeddings, no env LLM). Once the crawler stores our own page
 * content, this same endpoint serves the freshly-crawled corpus.
 */
export function useContentClusters() {
  return useQuery({
    queryKey: ['content-clusters'],
    queryFn: () => api.get<ContentClustersResponse>('/seo/content/clusters/'),
    staleTime: 60_000,
  });
}
