// useCancelSession.ts — POST /sessions/<uuid>/cancel/ mutation.
//
// On success, invalidates the active website's session list so the row's
// status flips from running/pending → cancelled on next refetch. The endpoint
// returns the updated CrawlSessionDetail; on 409 (already terminal) the
// shared apiFetch wrapper throws an ApiError whose `message` is the DRF
// `detail` field — surface that inline at the call site.

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';
import type { CrawlSessionDetail } from '../types';
import { sessionsQueryKey } from './useSessions';

export function useCancelSession(websiteId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      api.post<CrawlSessionDetail>(`/sessions/${sessionId}/cancel/`, {}),
    onSuccess: () => {
      if (websiteId) {
        qc.invalidateQueries({ queryKey: sessionsQueryKey(websiteId) });
      }
    },
  });
}
