// API client for the embedded crawler engine.
//
// After the crawler-engine -> Django port, every endpoint here is served by
// the Django backend under /api/v1/crawler/. In dev, Vite proxies
//   /crawler-api/<path>  ->  http://localhost:8000/api/v1/crawler/<path>
// (see frontend/web/vite.config.ts). The live-log stream is now a polling
// endpoint (/logs) — there is no WebSocket anymore.

const BASE = '/crawler-api';

async function request<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = (await res.json()) as { message?: string; error?: string };
      if (j.message || j.error) msg = (j.message || j.error)!;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  const ctype = res.headers.get('content-type') || '';
  if (ctype.includes('application/json')) return (await res.json()) as T;
  return res as unknown as T;
}

// ── Response shapes (loose; the Django backend owns the canonical schema) ──

export interface CrawlerStats {
  discovered: number;
  crawled: number;
  ok: number;
  errors: number;
  errors_404: number;
  queue_size: number;
  active_workers: number;
  started_at: number | null;
  finished_at: number | null;
}

export interface CrawlerStatus {
  is_running: boolean;
  should_stop: boolean;
  seed: string;
  allowed_domains: string[];
  stats: CrawlerStats;
  visited_count: number;
  queue_count: number;
}

export interface CrawlerSummary {
  pages_crawled: number;
  ok_pages: number;
  total_errors: number;
  errors_404: number;
  console_entries: number;
  discovered_edges: number;
  state: CrawlerStats | null;
}

export interface CategoryCounts {
  crawled?: number;
  ok?: number;
  errors?: number;
  errors_404?: number;
  indexed?: number;
  not_indexed?: number;
  excluded?: number;
  unknown_index?: number;
  from_sitemap?: number;
}

export interface CategoryMeta {
  key: string;
  label: string;
  subdomain: string;
  icon: string;
  counts: CategoryCounts;
}

export interface TableMeta {
  key: string;
  label: string;
  icon: string;
  description: string;
  count: number;
  categorized?: boolean;
  categories?: CategoryMeta[];
  by_subdomain?: Record<string, CategoryCounts>;
}

export interface TablesResponse {
  tables: TableMeta[];
  noise_404_branch_not_indexed?: number;
}

export interface TableData {
  key: string;
  label: string;
  icon: string;
  description: string;
  headers: string[];
  rows: string[][];
  count: number;
  filters?: ReportFilters;
}

export interface ReportFilters {
  subdomain?: string;
  category?: string;
  page_type?: string;
  indexed?: string; // comma-separated when multi-select
  from_sitemap?: string;
  hide_branch_404_noise?: boolean;
}

export interface SummaryBreakdown {
  by_subdomain: Record<string, CategoryCounts>;
  by_category: Record<string, CategoryCounts>;
  categories: CategoryMeta[];
  by_indexed_status: {
    indexed: number;
    not_indexed: number;
    excluded: number;
    unknown: number;
  };
  by_sitemap_source: {
    from_sitemap: number;
    discovered_only: number;
    unknown_source: number;
  };
  sitemap_failed_count: number;
  sitemap_404_count: number;
  by_error_type: {
    errors_404: number;
    errors_http: number;
    // errors_connection / errors_chunked retired — no UI surface uses them.
    console: number;
  };
  noise_404_branch_not_indexed: number;
}

export interface GscRefreshResponse {
  ok: boolean;
  loaded_urls: number;
}

export interface GscCoverageBuildResponse {
  ok: boolean;
  error?: string;
  coverage?: {
    output: string;
    indexed: number;
    not_indexed: number;
    excluded: number;
    unknown: number;
    indexed_urls_seen: number;
    sitemap_urls_seen: number;
    crawler_urls_seen: number;
    indexed_status_backfill?: {
      coverage_urls: number;
      files: Record<string, { status: string; updated: number }>;
    };
  };
  backfill?: {
    sitemap_urls: number;
    files: Record<string, { status: string; updated: number }>;
  };
}

export interface TreeNodeData {
  url: string;
  title: string;
  status_code: string;
  depth: number;
  total_children: number;
  children: TreeNodeData[];
}

export interface TreeResponse {
  root: TreeNodeData;
  total_edges: number;
  total_nodes_returned: number;
  max_depth: number;
  truncated: boolean;
}

export interface ActionResponse {
  ok: boolean;
  message?: string;
}

export interface CrawlerLogMessage {
  type?: string;
  message?: string;
  timestamp?: string;
  url?: string;
  depth?: number;
  new_links?: number;
  crawled?: number;
  queue_size?: number;
  discovered?: number;
  errors?: number;
  ok?: number;
  stats?: Partial<CrawlerStats>;
  is_running?: boolean;
}

export interface CrawlerLogsResponse {
  cursor: number;
  messages: CrawlerLogMessage[];
  is_running: boolean;
  stats: CrawlerStats;
}

function filterQuery(filters?: ReportFilters): string {
  if (!filters) return '';
  const qs = new URLSearchParams();
  if (filters.subdomain) qs.set('subdomain', filters.subdomain);
  if (filters.category) qs.set('category', filters.category);
  if (filters.page_type) qs.set('page_type', filters.page_type);
  if (filters.indexed) qs.set('indexed', filters.indexed);
  if (filters.from_sitemap) qs.set('from_sitemap', filters.from_sitemap);
  if (filters.hide_branch_404_noise) qs.set('hide_branch_404_noise', '1');
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export const crawlerApi = {
  status: () => request<CrawlerStatus>('/status'),
  summary: () => request<CrawlerSummary>('/summary'),
  breakdown: () => request<SummaryBreakdown>('/summary/breakdown'),
  tables: () => request<TablesResponse>('/tables'),
  table: (key: string, filters?: ReportFilters) =>
    request<TableData>(`/tables/${key}${filterQuery(filters)}`),
  tree: (maxDepth = 4, maxNodes = 3000) =>
    request<TreeResponse>(`/tree?max_depth=${maxDepth}&max_nodes=${maxNodes}`),
  start: () => request<ActionResponse>('/start', { method: 'POST' }),
  stop: () => request<ActionResponse>('/stop', { method: 'POST' }),
  logs: (cursor: number | null, limit = 500) => {
    const qs = new URLSearchParams();
    if (cursor !== null) qs.set('cursor', String(cursor));
    qs.set('limit', String(limit));
    return request<CrawlerLogsResponse>(`/logs?${qs.toString()}`);
  },
  downloadUrl: (key: string, filters?: ReportFilters) =>
    `${BASE}/download/${key}${filterQuery(filters)}`,
  xlsxUrl: () => `${BASE}/reports/xlsx`,
  refreshGscCoverage: () =>
    request<GscRefreshResponse>('/gsc/coverage/refresh', { method: 'POST' }),
  buildGscCoverage: (opts: { backfill?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (opts.backfill) qs.set('backfill', '1');
    const tail = qs.toString();
    return request<GscCoverageBuildResponse>(
      `/gsc/coverage/build${tail ? `?${tail}` : ''}`,
      { method: 'POST' },
    );
  },
  inspectGscUnknowns: (opts: { max?: number } = {}) => {
    const qs = new URLSearchParams();
    if (opts.max) qs.set('max', String(opts.max));
    const tail = qs.toString();
    return request<{
      ok: boolean;
      error?: string;
      inspected?: number;
      errors?: number;
      remaining?: number;
      msg?: string;
      backfill?: { files: Record<string, { status: string; updated: number }> };
    }>(`/gsc/coverage/inspect${tail ? `?${tail}` : ''}`, { method: 'POST' });
  },
  startConsoleCapture: (opts: {
    limit?: number;
    subdomain?: string;
    status?: string;
    levels?: string;
  } = {}) => {
    const qs = new URLSearchParams();
    if (opts.limit) qs.set('limit', String(opts.limit));
    if (opts.subdomain) qs.set('subdomain', opts.subdomain);
    if (opts.status) qs.set('status', opts.status);
    if (opts.levels) qs.set('levels', opts.levels);
    const tail = qs.toString();
    return request<{
      ok: boolean;
      message?: string;
      target_count?: number;
    }>(`/console/capture${tail ? `?${tail}` : ''}`, { method: 'POST' });
  },
  consoleCaptureStatus: () =>
    request<{
      is_running: boolean;
      should_stop: boolean;
      total: number;
      processed: number;
      failed: number;
      console_rows_written: number;
      last_url: string;
      started_at: number | null;
      finished_at: number | null;
    }>('/console/capture/status'),
  stopConsoleCapture: () =>
    request<{ ok: boolean; message?: string }>('/console/capture/stop', {
      method: 'POST',
    }),
};
