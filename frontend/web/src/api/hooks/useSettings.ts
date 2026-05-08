// useSettings.ts — TanStack Query hooks for the Settings screen.
//
// Backed by the standalone @api_view at:
//   GET   /api/v1/settings/?website=<uuid>  → SettingsDict
//   PATCH /api/v1/settings/?website=<uuid>  body: Partial<SettingsDict>
//                                           → SettingsDict
//
// The endpoint is keyed by the `website` query param (NOT a path PK), so
// the active-site toggle in the topbar maps cleanly to one URL. See
// backend/apps/crawler/views.py:settings_view (lines 542–576).
//
// Validation lives entirely server-side in SettingsService — on a 400 the
// service returns `{ "detail": "<field>: <reason>" }`. The shape is
// preserved on `ApiError.body` so SettingsPage can split on `: ` to surface
// the message inline next to the offending input.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';
import type { SettingsDict, SettingsUpdate } from '../types';

export function settingsQueryKey(websiteId: string | null) {
  // Object form keeps it stable for { website } predicate-style invalidation,
  // mirroring the convention in useSessions / usePages / useIssues.
  return ['settings', { website: websiteId }] as const;
}

export function useSettings(websiteId: string | null) {
  return useQuery({
    queryKey: settingsQueryKey(websiteId),
    queryFn: () =>
      api.get<SettingsDict>('/settings/', { website: websiteId ?? undefined }),
    enabled: websiteId !== null,
  });
}

export interface UpdateSettingsArgs {
  websiteId: string;
  payload: SettingsUpdate;
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ websiteId, payload }: UpdateSettingsArgs) =>
      // The fetch wrapper appends `?website=<id>` from the query map; the
      // body carries only the changed fields (PATCH semantics).
      api.patch<SettingsDict>(
        `/settings/?website=${encodeURIComponent(websiteId)}`,
        payload,
      ),
    onSuccess: (_data, variables) => {
      // Re-sync the form with server-truth (also catches any value the
      // server coerced, e.g. request_delay=2 → 2.0).
      queryClient.invalidateQueries({
        queryKey: settingsQueryKey(variables.websiteId),
      });
    },
  });
}
