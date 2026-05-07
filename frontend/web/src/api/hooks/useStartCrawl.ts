// useStartCrawl — POST /api/v1/websites/<uuid>/crawl/ to enqueue a crawl.
//
// Returns 202 with { message, task_id, website_id }. On success we
// invalidate Stream F's session list cache so the freshly-created
// pending session appears immediately on the Sessions page.
//
// IMPORTANT: the invalidation key MUST be ['sessions', { website: id }]
// (tuple of [string, object]) — Stream F's useSessions matches this
// exact shape. Do not change without coordinating.

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../client';
import type { CrawlTriggeredResponse } from '../types';

export function useStartCrawl() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (websiteId: string) =>
      api.post<CrawlTriggeredResponse>(`/websites/${websiteId}/crawl/`, {}),
    onSuccess: (_data, websiteId) => {
      queryClient.invalidateQueries({
        queryKey: ['sessions', { website: websiteId }],
      });
    },
  });
}
