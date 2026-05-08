// useSystemMetrics.ts — TanStack Query hook for the System Metrics card
// (Spec §4.2 / §5.4.1).
//
// Backed by:
//   GET /api/v1/system/metrics/   → SystemHostMetrics
//
// Returns a snapshot of host CPU/memory, Redis broker queue depth, and
// Celery worker activity. Distinct from the *crawl-perf* metrics on
// OverviewService — those continue to flow through useOverview().
//
// Polling cadence: 5s. System load changes slowly enough that a tighter
// refresh would just churn re-renders; staleTime is set just below the
// interval so a quick remount reuses the cached value.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { SystemHostMetrics } from '../types';

export const systemMetricsQueryKey = ['system-metrics'] as const;

export function useSystemMetrics() {
  return useQuery({
    queryKey: systemMetricsQueryKey,
    queryFn: () => api.get<SystemHostMetrics>('/system/metrics/'),
    refetchInterval: 5000,
    staleTime: 4000,
  });
}
