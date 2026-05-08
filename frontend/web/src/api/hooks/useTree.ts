// useTree.ts — TanStack Query hook for the Visualizations page site tree.
//
// Backed by:
//   GET /sessions/<uuid>/tree/?max_depth=<int>  → SiteTree
//
// The tree is built server-side by TreeService.build_tree (see backend/apps/
// crawl_sessions/services/tree_service.py). `max_depth` is clamped to 1..10
// by the view; we send the user's selection through verbatim and let the
// backend handle out-of-range values.

import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import type { SiteTree } from '../types';

export function treeQueryKey(sessionId: string | null, maxDepth: number) {
  // Object form keeps the key stable for { session } predicate-style
  // invalidation, mirroring useSessions / useIssues. `maxDepth` is part
  // of the key so each depth setting caches independently.
  return ['tree', { session: sessionId, maxDepth }] as const;
}

export function useTree(sessionId: string | null, maxDepth: number = 4) {
  return useQuery({
    queryKey: treeQueryKey(sessionId, maxDepth),
    queryFn: () =>
      api.get<SiteTree>(`/sessions/${sessionId}/tree/`, {
        max_depth: maxDepth,
      }),
    enabled: sessionId !== null,
  });
}
