/**
 * Custodians dashboard — backed by /api/v1/seo/custodians/summary/.
 *
 * Returns OurDataCustodian (the bajajlifeinsurance.com summary) side-
 * by-side with TheirDataCustodian for every competitor in the roster,
 * plus the SiteDiffer report (page-count delta, schema gaps, link-kind
 * gaps, CWV deltas).
 */
import { useQuery } from '@tanstack/react-query';
import { api } from '../client';

export interface DomainSummary {
  domain: string;
  is_ours: boolean;
  snapshot_id: string | null;
  snapshot_date: string | null;
  page_count: number;
  ok_page_count: number;
  median_word_count: number;
  avg_word_count: number;
  has_schema_pct: number;
  avg_pagespeed_score: number | null;
  median_lcp_ms: number | null;
  median_cls: number | null;
  median_inp_ms: number | null;
  page_types: Record<string, number>;
  schema_types: string[];
  top_internal_link_kinds: Array<[string, number]>;
  top_headings: string[];
  recent_changes: Record<string, number>;
  recent_change_urls: Array<{
    url: string;
    kind: string;
    detected_at: string;
    delta: Record<string, unknown>;
  }>;
}

export interface DiffReport {
  our_domain: string;
  their_domains: string[];
  page_count_delta: Record<string, number>;
  schema_only_theirs: Record<string, string[]>;
  schema_only_ours: string[];
  page_type_gaps: Record<string, Record<string, number>>;
  link_kind_gaps: Record<string, string[]>;
  cwv_deltas: Record<
    string,
    Record<string, { ours: number | null; theirs: number | null; diff: number | null } | null>
  >;
}

export interface CustodiansResponse {
  our: DomainSummary;
  competitors: DomainSummary[];
  roster_size: number;
  diff?: DiffReport;
}

export function useCustodiansSummary() {
  return useQuery({
    queryKey: ['custodians-summary'],
    queryFn: () => api.get<CustodiansResponse>('/seo/custodians/summary/'),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
