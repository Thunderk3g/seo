// useWebsites — TanStack Query hook listing all registered websites.
// Backed by GET /api/v1/websites/ (the API_BASE prefix is in client.ts).
//
// Export the query key as a stable tuple so other hooks (createWebsite,
// future websiteDetail invalidations) can reference the same identity
// without drift.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { Website } from '../types';

export const websitesQueryKey = ['websites'] as const;

export function useWebsites() {
  return useQuery({
    queryKey: websitesQueryKey,
    queryFn: () => api.get<Website[]>('/websites/'),
  });
}
