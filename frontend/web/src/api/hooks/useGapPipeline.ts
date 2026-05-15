// useGapPipeline — orchestrates the polling lifecycle for one Phase-3
// gap pipeline run.
//
// Two layered queries:
//
//   1. ``status`` (lightweight)  — header + stage_status JSON. Polled
//      every 3 seconds while the run is in progress; stops polling
//      once status hits a terminal state (complete/degraded/failed).
//   2. ``detail`` (full payload) — every child table. Fetched once on
//      mount AND any time the lightweight status reports a new stage
//      transition, so the panels paint with the freshest child data.
//
// Also exposes ``latest(domain)`` so the page can resolve a recent run
// before showing the "Run pipeline" CTA, and ``start(domain)`` for the
// CTA itself.

import { useEffect, useMemo } from 'react';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from '@tanstack/react-query';
import { api } from '../client';
import type {
  GapPipelineDetail,
  GapPipelineLatest,
  GapPipelineRunHeader,
  GapPipelineStartResponse,
} from '../seoTypes';

const TERMINAL = new Set(['complete', 'degraded', 'failed']);

export function useLatestGapPipeline(domain: string) {
  return useQuery({
    queryKey: ['seo', 'gap-pipeline', 'latest', domain],
    queryFn: () =>
      api.get<GapPipelineLatest>('/seo/gap-pipeline/latest/', { domain }),
    staleTime: 30 * 1000,
  });
}

export function useStartGapPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      domain: string;
      top_n?: number;
      query_count?: number;
    }) => api.post<GapPipelineStartResponse>('/seo/gap-pipeline/start/', vars),
    onSuccess: (_, vars) => {
      // Invalidate the latest-run lookup so the next render picks up
      // the brand-new run id without waiting for the natural refetch.
      qc.invalidateQueries({
        queryKey: ['seo', 'gap-pipeline', 'latest', vars.domain],
      });
    },
  });
}

export function useGapPipelineStatus(runId: string | undefined) {
  return useQuery({
    queryKey: ['seo', 'gap-pipeline', 'status', runId] as QueryKey,
    queryFn: () =>
      api.get<GapPipelineRunHeader>(
        `/seo/gap-pipeline/${runId}/status/`,
      ),
    enabled: Boolean(runId),
    // Poll every 3 sec while the run is in progress.
    refetchInterval: (q) => {
      const data = q.state.data as GapPipelineRunHeader | undefined;
      if (!data) return 3000;
      if (TERMINAL.has(data.status)) return false;
      return 3000;
    },
  });
}

export function useGapPipelineDetail(runId: string | undefined) {
  const qc = useQueryClient();
  // Stage-status fingerprint we watch to know when to re-fetch detail.
  const statusData = qc.getQueryData<GapPipelineRunHeader>([
    'seo',
    'gap-pipeline',
    'status',
    runId,
  ]);
  const fingerprint = useMemo(() => {
    if (!statusData) return '';
    return [
      statusData.status,
      ...Object.entries(statusData.stage_status || {}).map(
        ([k, v]) => `${k}:${v?.status ?? '-'}`,
      ),
    ].join('|');
  }, [statusData]);

  const query = useQuery({
    queryKey: [
      'seo',
      'gap-pipeline',
      'detail',
      runId,
      fingerprint,
    ] as QueryKey,
    queryFn: () =>
      api.get<GapPipelineDetail>(`/seo/gap-pipeline/${runId}/`),
    enabled: Boolean(runId),
    staleTime: 5 * 1000,
  });

  // Side-effect: whenever the status fingerprint changes we want a
  // fresh detail fetch. We use the queryKey above to invalidate on the
  // fingerprint diff — but TanStack already does that for us by virtue
  // of including ``fingerprint`` in the key. This effect is just for
  // explicit prefetch after a stage transition completes.
  useEffect(() => {
    if (!runId) return;
    if (!statusData) return;
    if (TERMINAL.has(statusData.status)) {
      qc.invalidateQueries({
        queryKey: ['seo', 'gap-pipeline', 'detail', runId],
      });
    }
  }, [runId, statusData?.status, qc, statusData]);

  return query;
}
