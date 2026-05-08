// useIssues.ts — TanStack Query hooks for the Issues screen.
//
// Backed by:
//   GET /sessions/<uuid>/issues/             → IssueSummary[]
//   GET /sessions/<uuid>/issues/<issue_id>/  → IssueDetail
//
// Both are derived server-side by IssueService (see backend/apps/
// crawl_sessions/services/issue_service.py). The summary list is small
// (~12 categories) so we don't paginate; the detail endpoint owns the
// affected_urls payload.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { IssueSummary, IssueDetail } from '../types';

export function issuesQueryKey(sessionId: string | null) {
  // Object form keeps it stable for { session } predicate-style invalidation,
  // mirroring the convention in useSessions / usePages.
  return ['issues', { session: sessionId }] as const;
}

export function issueDetailQueryKey(
  sessionId: string | null,
  issueId: string | null,
) {
  return ['issue-detail', { session: sessionId, issueId }] as const;
}

export function useIssues(sessionId: string | null) {
  return useQuery({
    queryKey: issuesQueryKey(sessionId),
    queryFn: () =>
      api.get<IssueSummary[]>(`/sessions/${sessionId}/issues/`),
    enabled: sessionId !== null,
  });
}

export function useIssueDetail(
  sessionId: string | null,
  issueId: string | null,
) {
  return useQuery({
    queryKey: issueDetailQueryKey(sessionId, issueId),
    queryFn: () =>
      api.get<IssueDetail>(`/sessions/${sessionId}/issues/${issueId}/`),
    enabled: sessionId !== null && issueId !== null,
  });
}
