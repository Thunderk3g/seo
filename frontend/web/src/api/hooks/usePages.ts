// usePages.ts — TanStack Query hook for the Pages/URLs screen.
//
// Backed by GET /sessions/<uuid>/pages/ which now returns a DRF
// PageNumberPagination envelope. Filters/sort/search/pagination are passed
// as query params; the backend whitelists ordering columns and content-type
// buckets.

import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../client';
import type { PageListItem, PaginatedResponse } from '../types';

export type StatusClass = '' | '2xx' | '3xx' | '4xx' | '5xx';
export type ContentTypeBucket = '' | 'all' | 'html' | 'image' | 'css' | 'js';

export interface PagesQueryArgs {
  sessionId: string | null;
  page?: number;
  pageSize?: number;
  statusClass?: StatusClass;
  contentType?: ContentTypeBucket;
  q?: string;
  ordering?: string;
}

export function pagesQueryKey(args: PagesQueryArgs) {
  const {
    sessionId, page = 1, pageSize = 50, statusClass = '',
    contentType = '', q = '', ordering = '',
  } = args;
  return [
    'pages',
    {
      session: sessionId,
      page, pageSize, statusClass, contentType, q, ordering,
    },
  ] as const;
}

export function usePages(args: PagesQueryArgs) {
  return useQuery({
    queryKey: pagesQueryKey(args),
    queryFn: () => {
      const query: Record<string, string | number> = {
        page: args.page ?? 1,
        page_size: args.pageSize ?? 50,
      };
      if (args.statusClass) query.status_class = args.statusClass;
      if (args.contentType && args.contentType !== 'all')
        query.content_type = args.contentType;
      if (args.q) query.q = args.q;
      if (args.ordering) query.ordering = args.ordering;
      return api.get<PaginatedResponse<PageListItem>>(
        `/sessions/${args.sessionId}/pages/`,
        query,
      );
    },
    enabled: args.sessionId !== null,
    placeholderData: keepPreviousData, // smooth pagination — keeps old rows on flip
  });
}
