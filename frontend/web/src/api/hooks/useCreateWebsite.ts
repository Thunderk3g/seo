// useCreateWebsite — POST /api/v1/websites/ to register a new site.
//
// On success: invalidates the ['websites'] list query and promotes the
// newly-created site to the active selection so the topbar / sidebar
// switch over without an extra click.
//
// DRF returns 400 with `{ field: ["msg"] }` on validation errors; the
// shape is preserved on the thrown `ApiError.body` so callers can pull
// field-specific messages out of `error.body` (see AddSiteModal).

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';
import type { Website, WebsiteCreate } from '../types';
import { websitesQueryKey } from './useWebsites';
import { useActiveSite } from './useActiveSite';

export function useCreateWebsite() {
  const queryClient = useQueryClient();
  const { setActiveSite } = useActiveSite();

  return useMutation({
    mutationFn: (body: WebsiteCreate) => api.post<Website>('/websites/', body),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: websitesQueryKey });
      setActiveSite(created.id);
    },
  });
}
