/**
 * ContentWriter — LLM-driven rewrites grounded in real evidence.
 *
 * Backed by /api/v1/seo/content-writer/. Pulls the list of crawled
 * URLs the writer can target, generates a rewrite proposal, and lists
 * recent proposals so the operator can revisit them.
 *
 * The proposal's source-of-truth is the deterministic critic verdict:
 * every generated string has a ``source_ref`` and a backend pass drops
 * anything that doesn't resolve into the evidence dict.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';

export interface OurPageSummary {
  url: string;
  title: string;
  page_type: string;
  word_count: number;
}

export interface OurPagesResponse {
  snapshot_id: string | null;
  snapshot_date: string | null;
  pages: OurPageSummary[];
}

export interface CitedString {
  text: string;
  source_ref: string;
  rationale?: string;
}

export interface CitedHeading {
  level: number;
  text: string;
  source_ref: string;
  rationale?: string;
}

export interface CitedLink {
  anchor: string;
  target_url: string;
  section?: string;
  source_ref: string;
  rationale?: string;
}

export interface RewriteProposalBody {
  proposed_title?: CitedString;
  proposed_meta_description?: CitedString;
  proposed_headings?: CitedHeading[];
  proposed_internal_links?: CitedLink[];
  overall_rationale?: string;
}

export interface CriticVerdict {
  accepted: number;
  rejected: number;
  rejected_items: Array<{
    path: string;
    source_ref: string | null;
    reason: string;
  }>;
}

export interface ContentRewriteProposal {
  id: string;
  our_url: string;
  competitor_urls: string[];
  target_keywords: string[];
  evidence_dict: Record<string, unknown>;
  generated_proposal: RewriteProposalBody;
  raw_proposal: RewriteProposalBody;
  critic_verdict: CriticVerdict;
  model_used: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  error: string;
  created_at: string;
}

export interface ProposalListEntry {
  id: string;
  our_url: string;
  model_used: string;
  accepted: number;
  rejected: number;
  cost_usd: number;
  error: string;
  created_at: string;
}

// ── hooks ─────────────────────────────────────────────────────────────

const OUR_PAGES_KEY = ['content-writer', 'our-pages'] as const;
const LIST_KEY = ['content-writer', 'proposals'] as const;

export function useContentWriterOurPages() {
  return useQuery({
    queryKey: OUR_PAGES_KEY,
    queryFn: () => api.get<OurPagesResponse>('/seo/content-writer/our-pages/'),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useContentWriterProposals() {
  return useQuery({
    queryKey: LIST_KEY,
    queryFn: () =>
      api.get<{ count: number; proposals: ProposalListEntry[] }>(
        '/seo/content-writer/proposals/',
      ),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useContentWriterProposal(id: string | null) {
  return useQuery({
    queryKey: ['content-writer', 'proposal', id],
    queryFn: () =>
      api.get<ContentRewriteProposal>(
        `/seo/content-writer/proposals/${id}/`,
      ),
    enabled: Boolean(id),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export interface GenerateRewriteInput {
  our_url: string;
  competitor_urls?: string[];
  target_keywords?: string[];
}

export function useGenerateRewrite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GenerateRewriteInput) =>
      api.post<ContentRewriteProposal>(
        '/seo/content-writer/generate/',
        body,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}
