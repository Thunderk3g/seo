// Hooks for the SEO grading runs.
//
// Five hooks total:
//   useGradeList       → GET /seo/grade/                  list recent runs
//   useGrade(id)       → GET /seo/grade/<id>/             one run header
//   useGradeFindings   → GET /seo/grade/<id>/findings/    findings table
//   useGradeMessages   → GET /seo/grade/<id>/messages/    agent conversation
//   useStartGrade      → POST /seo/grade/start/           kick off a run
//
// Running runs poll every 5 s so the UI reflects status transitions
// (running → critic → complete/degraded). Completed runs are
// effectively static, so they're queried once and cached.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { api } from '../client';
import type {
  SEORun,
  SEORunFinding,
  SEORunMessage,
} from '../seoTypes';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

export const gradeKeys = {
  list: (domain?: string) =>
    ['seo-grade', 'list', { domain: domain ?? DEFAULT_DOMAIN }] as const,
  detail: (id: string | null) =>
    ['seo-grade', 'detail', { id }] as const,
  findings: (id: string | null, agent: string | null) =>
    ['seo-grade', 'findings', { id, agent }] as const,
  messages: (id: string | null) =>
    ['seo-grade', 'messages', { id }] as const,
};


export function useGradeList(domain: string = DEFAULT_DOMAIN) {
  return useQuery({
    queryKey: gradeKeys.list(domain),
    queryFn: () => api.get<SEORun[]>('/seo/grade/', { domain }),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useGrade(id: string | null) {
  return useQuery({
    queryKey: gradeKeys.detail(id),
    queryFn: () => api.get<SEORun>(`/seo/grade/${id}/`),
    enabled: Boolean(id),
    // Poll while the run is still moving through stages. Stops polling
    // automatically once status is complete/degraded/failed.
    refetchInterval: (query) => {
      const status = (query.state.data as SEORun | undefined)?.status;
      if (!status) return 5_000;
      const terminal = ['complete', 'degraded', 'failed'];
      return terminal.includes(status) ? false : 5_000;
    },
  });
}

export function useGradeFindings(
  id: string | null,
  agent?: 'technical' | 'keyword' | 'content' | 'competitor' | null,
) {
  const agentParam = agent ?? null;
  return useQuery({
    queryKey: gradeKeys.findings(id, agentParam),
    queryFn: () =>
      api.get<SEORunFinding[]>(`/seo/grade/${id}/findings/`, {
        agent: agentParam ?? undefined,
      }),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}

export function useGradeMessages(id: string | null) {
  return useQuery({
    queryKey: gradeKeys.messages(id),
    queryFn: () => api.get<SEORunMessage[]>(`/seo/grade/${id}/messages/`),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}

export interface StartGradeResponse {
  id: string;
  status: string;
}

export function useStartGrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { domain?: string; sync?: boolean }) => {
      const domain = input.domain ?? DEFAULT_DOMAIN;
      return api.post<StartGradeResponse>('/seo/grade/start/', {
        domain,
        sync: input.sync ?? false,
      });
    },
    onSuccess: (_data, input) => {
      qc.invalidateQueries({
        queryKey: gradeKeys.list(input.domain ?? DEFAULT_DOMAIN),
      });
      qc.invalidateQueries({ queryKey: ['seo-overview'] });
    },
  });
}
