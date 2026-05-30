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

export interface CitedBodySection {
  heading_text: string;
  paragraphs: string[];
  source_ref: string;
  rationale?: string;
}

export interface CitedFaqEntry {
  question: string;
  answer: string;
  source_ref: string;
  rationale?: string;
}

export interface CitedCta {
  text: string;
  placement?: string;
  source_ref: string;
}

export interface TechRecommendation {
  area: string;          // 'lcp' | 'cls' | 'inp' | 'pagespeed' | 'schema'
  current?: string;
  target?: string;
  suggestion: string;
  source_ref: string;
}

export interface CompetitorGapSummary {
  brand: string;
  gap: string;
}

export interface RewriteProposalBody {
  proposed_title?: CitedString;
  proposed_meta_description?: CitedString;
  proposed_headings?: CitedHeading[];
  proposed_internal_links?: CitedLink[];
  // Revamp-flow additions (Phase F2).
  proposed_body_sections?: CitedBodySection[];
  proposed_faq?: CitedFaqEntry[];
  proposed_ctas?: CitedCta[];
  tech_recommendations?: TechRecommendation[];
  improved_html?: string;
  improved_markdown?: string;
  competitor_gap_summary?: CompetitorGapSummary[];
  overall_rationale?: string;
}

export interface CompetitorMatch {
  brand: string;
  url: string;
  title: string;
  confidence: number;
  source: 'db' | 'live' | string;
  snapshot_id: string;
  word_count: number;
}

export interface RevampTelemetry {
  competitors_scanned: number;
  competitors_matched: number;
  warnings: string[];
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

export interface GapSectionMissByUs {
  name: string;
  label: string;
  brands_with_it: string[];
  topics_aggregate: string[];
  sample_headings: string[];
}

export interface GapSectionUniqueToUs {
  name: string;
  label: string;
  sample_headings: string[];
}

export interface GapSizeDiff {
  our_word_count: number;
  median_their_word_count: number;
  deficit: number;
  our_heading_count: number;
  median_their_heading_count: number;
  our_image_count: number;
  median_their_image_count: number;
}

export interface GapLinkInventoryDiff {
  our_total: number;
  median_their_total: number;
  our_by_kind: Record<string, number>;
  median_their_by_kind: Record<string, number>;
  kinds_we_lack: string[];
}

export interface GapFooterDiff {
  our_footer_link_count: number;
  median_their_footer_link_count: number;
}

export interface GapTopicOverlap {
  overlap_pct: number;
  our_unique_topics: string[];
  their_aggregate_unique_topics: string[];
}

export interface CompetitorGap {
  sections_we_miss: GapSectionMissByUs[];
  sections_unique_to_us: GapSectionUniqueToUs[];
  size_diff: GapSizeDiff | null;
  link_inventory_diff: GapLinkInventoryDiff | null;
  footer_diff: GapFooterDiff | null;
  topic_overlap: GapTopicOverlap | null;
  headline_recommendations: string[];
}

export interface OurSectionsEntry {
  section_id: number;
  name: string;
  rationale: string;
  topics_covered: string[];
  heading_texts: string[];
  internal_links: { anchor: string; href: string; kind: string }[];
  image_count: number;
  word_count: number;
}

export interface TheirSectionsEntry {
  brand: string;
  sections: OurSectionsEntry[];
}

export interface ContentRewriteProposal {
  id: string;
  our_url: string;
  competitor_urls: string[];
  target_keywords: string[];
  prompt_instructions?: string;
  competitor_matches?: CompetitorMatch[];
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
  telemetry?: RevampTelemetry;
  // Cluster-first orchestrator output (Phase F5).
  our_sections?: OurSectionsEntry[];
  their_sections?: TheirSectionsEntry[];
  gap?: CompetitorGap;
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

// Phase F2 — single-URL revamp flow.
export interface RevampInput {
  our_url: string;
  prompt?: string;
  max_competitors?: number;
  enable_psi?: boolean;
  enable_semrush?: boolean;
}

export function useRevampPage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RevampInput) =>
      api.post<ContentRewriteProposal>(
        '/seo/content-writer/revamp/',
        body,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}
