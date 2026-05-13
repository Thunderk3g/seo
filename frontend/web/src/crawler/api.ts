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

export interface TableMeta {
  key: string;
  label: string;
  icon: string;
  description: string;
  count: number;
}

export interface TableData {
  key: string;
  label: string;
  icon: string;
  description: string;
  headers: string[];
  rows: string[][];
  count: number;
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

export const crawlerApi = {
  status: () => request<CrawlerStatus>('/status'),
  summary: () => request<CrawlerSummary>('/summary'),
  tables: () => request<{ tables: TableMeta[] }>('/tables'),
  table: (key: string) => request<TableData>(`/tables/${key}`),
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
  downloadUrl: (key: string) => `${BASE}/download/${key}`,
  xlsxUrl: () => `${BASE}/reports/xlsx`,
};
