// useExports.ts — TanStack Query hooks for the Exports screen.
//
// Backed by:
//   GET  /sessions/<uuid>/exports/                  → ExportRecordSummary[]
//   POST /sessions/<uuid>/exports/<kind>/           → ExportRecordSummary (201)
//
// The download endpoint
//   GET  /sessions/<uuid>/exports/<export-uuid>/download/
// is consumed via a plain <a href download> in the page — it returns a
// non-JSON file body with Content-Disposition, so it does NOT go through
// the api client.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';
import type { ExportKind, ExportRecordSummary } from '../types';

export function exportsQueryKey(sessionId: string | null) {
  // Object form keeps it stable for { session } predicate-style invalidation,
  // mirroring useIssues / useSessions / usePages.
  return ['exports', { session: sessionId }] as const;
}

export function useExports(sessionId: string | null) {
  return useQuery({
    queryKey: exportsQueryKey(sessionId),
    queryFn: () =>
      api.get<ExportRecordSummary[]>(`/sessions/${sessionId}/exports/`),
    enabled: sessionId !== null,
  });
}

interface CreateExportArgs {
  sessionId: string;
  kind: ExportKind;
}

export function useCreateExport() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ sessionId, kind }: CreateExportArgs) =>
      api.post<ExportRecordSummary>(
        `/sessions/${sessionId}/exports/${kind}/`,
        {},
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: exportsQueryKey(variables.sessionId),
      });
    },
  });
}
