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

  // PSI / Core Web Vitals — last-run status. Returns {} (empty object)
  // when no PSI run has happened yet. When a run completed, this carries
  // ok / urls_inspected / rows_written / failed / error so the UI can
  // render either a success or a "PSI skipped because <reason>" banner.
  psiStatus: () =>
    request<{
      ok?: boolean;
      started_at?: string;
      finished_at?: string;
      urls_inspected?: number;
      rows_written?: number;
      failed?: number;
      strategies?: string[];
      primary_strategy?: string;
      error?: string;
      mode?: string;
    }>('/psi/status'),

  // Live progress of the inline PSI scheduler while a crawl is running.
  // Returns {} when no crawl/scheduler is in flight. While active,
  // exposes per-URL counters so the banner can render a live progress
  // bar instead of waiting for the end-of-crawl summary.
  psiProgress: () =>
    request<{
      is_running?: boolean;
      started_at?: number;
      finished_at?: number;
      submitted?: number;
      in_flight?: number;
      completed?: number;
      failed?: number;
      queue_size?: number;
      last_url?: string;
      workers?: number;
      strategies?: string[];
      primary_strategy?: string;
      disabled?: boolean;
      disabled_reason?: string;
    }>('/psi/progress'),

  // Audit engine — Health Score KPI (Phase 1).
  // Computes the Ahrefs-formula Health Score over the current
  // crawl_results.csv: (URLs without any error-severity issue / total
  // URLs) × 100. Returns score, tier (Excellent/Good/Fair/Weak),
  // severity counts, per-category type counts, and the top-5 errors.
  healthScore: () =>
    request<{
      score: number;
      tier: 'Excellent' | 'Good' | 'Fair' | 'Weak';
      total_urls: number;
      urls_without_error: number;
      urls_with_any_error: number;
      severity_counts: { error: number; warning: number; notice: number };
      issue_type_counts: { error: number; warning: number; notice: number };
      category_counts: Record<string, number>;
      top_errors: Array<{
        slug: string;
        title: string;
        severity: string;
        category: string;
        why: string;
        how_to_fix: string;
        count: number;
      }>;
      formula: string;
      started_at: string;
      finished_at: string;
    }>('/health-score'),

  // Audit engine — Issues triage inbox (Phase 1).
  // Lists every issue type detected, sorted errors first then by URL
  // count. Filterable by severity and category via query params.
  issues: (params?: { severity?: string; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.category) qs.set('category', params.category);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<{
      total_urls: number;
      ok_urls: number;
      severity_counts: { error: number; warning: number; notice: number };
      issue_type_counts: { error: number; warning: number; notice: number };
      issues: Array<{
        slug: string;
        title: string;
        severity: 'error' | 'warning' | 'notice';
        category: string;
        why: string;
        how_to_fix: string;
        count: number;
      }>;
      started_at: string;
      finished_at: string;
    }>(`/issues${suffix}`);
  },

  // Per-issue drill-in. Returns metadata + the list of affected URLs
  // (capped at 1000 server-side to keep payloads bounded). Used by
  // IssueDetailPage and the chat agent when a user asks "show me the
  // URLs hit by X".
  issueDetail: (slug: string) =>
    request<{
      slug: string;
      title: string;
      severity: string;
      category: string;
      why: string;
      how_to_fix: string;
      count: number;
      affected_urls: Array<{
        url: string;
        title: string;
        status_code: string;
        subdomain: string;
        page_type: string;
        word_count: string;
        response_time_ms: string;
        indexed_status: string;
      }>;
      started_at: string;
    }>(`/issues/${encodeURIComponent(slug)}`),

  // Compliance dashboard — WCAG / GDPR / OWASP aggregated payload.
  // Designed for the manager-facing report; per-URL evidence comes
  // pre-populated so the front-end stays presentational only.
  compliance: () =>
    request<{
      started_at: string;
      summary: {
        total_violations: number;
        unique_rules_failed: number;
        pages_audited: number;
        pages_with_any_violation: number;
        by_severity: { error: number; warning: number; notice: number };
        by_section: Record<string, number>;
      };
      sections: Array<{
        key: string;
        title: string;
        total_violations: number;
        rules: Array<{
          slug: string;
          title: string;
          severity: 'error' | 'warning' | 'notice';
          category: string;
          why: string;
          how_to_fix: string;
          references: Array<{
            standard: string;
            ref: string;
            level?: string;
            name: string;
          }>;
          count: number;
          affected_urls: Array<{
            url: string;
            title: string;
            subdomain: string;
            page_type: string;
            evidence: string;
          }>;
        }>;
      }>;
    }>('/compliance'),

  // 3D content map — Phase 3 of the content classification pipeline.
  // Returns UMAP-projected chunk embeddings with classification labels
  // ready for direct rendering.
  contentMap3d: () =>
    request<{
      snapshot_id: string;
      snapshot_date: string;
      total: number;
      points: Array<{
        id: number;
        chunk_idx: number;
        x: number;
        y: number;
        z: number;
        url: string;
        title: string;
        products: string[];
        page_type: string;
        confidence: number;
      }>;
    }>('/content/map/3d'),

  // Similarity search — pages most similar to a URL or free text.
  contentSimilar: (params: { url?: string; query?: string; product?: string;
                              page_type?: string; top_k?: number }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') qs.set(k, String(v));
    });
    return request<{
      results: Array<{
        url: string;
        title: string;
        page_type: string;
        products: string[];
        similarity: number;
      }>;
    }>(`/content/similar?${qs.toString()}`);
  },

  // Phase 1c — Hierarchical content cluster tree (Product → Page-type → pages).
  // Pure rule-based; works without embeddings. `mode` toggles between
  // single-primary-product and multi-label assignment.
  // `domain` resolves to the latest non-empty competitor snapshot for that
  // host. No domain + no snapshot = latest Bajaj (ours-side default).
  contentClusters: (params: { snapshot?: string; domain?: string; mode?: 'primary' | 'multi' } = {}) => {
    const qs = new URLSearchParams();
    if (params.snapshot) qs.set('snapshot', params.snapshot);
    if (params.domain) qs.set('domain', params.domain);
    if (params.mode) qs.set('mode', params.mode);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<{
      snapshot_id: string;
      snapshot_date: string;
      mode: 'primary' | 'multi';
      totals: {
        pages: number;
        classified: number;
        uncertain: number;
        assignments: number;
      };
      products: Array<{
        product: string;
        label: string;
        count: number;
        page_types: Array<{
          page_type: string;
          label: string;
          count: number;
          pages: Array<{
            url: string;
            title: string;
            confidence: number;
            tier: number;
            products: string[];
            page_type: string;
          }>;
        }>;
      }>;
      uncertain: {
        count: number;
        pages: Array<{
          url: string;
          title: string;
          confidence: number;
          tier: number;
          products: string[];
          page_type: string;
        }>;
      };
    }>(`/content/clusters${suffix}`);
  },

  // Pickable snapshots — feeds the cluster + map picker so the
  // operator can switch between Bajaj and competitor snapshots.
  snapshots: () =>
    request<{
      count: number;
      snapshots: Array<{
        id: string;
        started_at: string | null;
        kind: string;
        engine: string;
        target_domain: string;
        page_count: number;
        ok_page_count: number;
        health_score: number | null;
        status: string;
      }>;
    }>('/snapshots'),

  // Phase 2 — Page Explorer (Ahrefs-style sortable/filterable URL
  // inventory). Server-side sort + filter; pass query params 1:1.
  pages: (params: {
    sort?: string;
    status?: string;
    subdomain?: string;
    page_type?: string;
    indexed?: string;
    has_psi?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && String(v) !== '') {
        qs.set(k, String(v));
      }
    });
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<{
      total: number;
      returned: number;
      limit: number;
      offset: number;
      sort: string;
      rows: Array<Record<string, string>>;
      columns: string[];
    }>(`/pages${suffix}`);
  },

  pagesFacets: () =>
    request<{
      status_code: string[];
      subdomain: string[];
      page_type: string[];
      indexed_status: string[];
    }>('/pages/facets'),

  // Phase 4 — Internal PageRank ("Link Score" / Ahrefs Page Rating).
  pagerank: () =>
    request<{
      summary: {
        computed: boolean;
        node_count: number;
        edge_count: number;
        top_url: string | null;
        top_score?: number;
        orphan_count: number;
      };
      top: Array<{
        url: string;
        pagerank: number;
        pagerank_score: number;
        in_degree: number;
        out_degree: number;
      }>;
    }>('/pagerank'),

  // Phase 5 — Daily Health Score trend snapshots.
  trends: (params?: { window?: number; engine?: string }) => {
    const qs = new URLSearchParams();
    if (params?.window !== undefined) qs.set('window', String(params.window));
    if (params?.engine) qs.set('engine', params.engine);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<{
      engine: string;
      window: number;
      snapshot_count: number;
      snapshots: Array<{
        recorded_date: string;
        engine: string;
        health_score: number | null;
        health_tier: string;
        pages_attempted: number;
        pages_ok: number;
        pages_errored: number;
        errors: number;
        warnings: number;
        notices: number;
        issue_counts: Record<string, number>;
        category_counts: Record<string, number>;
        pagerank_node_count: number;
        pagerank_orphan_count: number;
        near_dup_cluster_count: number;
        near_dup_total_dupes: number;
      }>;
    }>(`/trends${suffix}`);
  },

  // Phase 5 — SEMrush-style Compare Crawls diff.
  compare: (params?: { a?: string; b?: string }) => {
    const qs = new URLSearchParams();
    if (params?.a) qs.set('a', params.a);
    if (params?.b) qs.set('b', params.b);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<{
      a_snapshot_id: string;
      b_snapshot_id: string;
      a_started_at: string;
      b_started_at: string;
      a_engine: string;
      b_engine: string;
      a_health_score: number | null;
      b_health_score: number | null;
      health_score_delta: number | null;
      issues: Array<{
        slug: string;
        title: string;
        severity: string;
        category: string;
        a_count: number;
        b_count: number;
        delta: number;
        fixed_urls: string[];
        new_urls: string[];
        changed_urls: string[];
      }>;
      pages_added: Array<{ url: string; b_status: string; b_word_count: number }>;
      pages_removed: Array<{ url: string; a_status: string; a_word_count: number }>;
      pages_status_changed: Array<{
        url: string;
        a_status: string; b_status: string;
        a_word_count: number; b_word_count: number;
      }>;
      fixed_count: number;
      new_count: number;
      changed_count: number;
    }>(`/compare${suffix}`);
  },

  // Phase 5 — Thematic deep-dive reports.
  themesList: () =>
    request<{ themes: Array<{ slug: string; title: string; description: string }> }>('/themes'),

  themeDetail: (slug: string) =>
    request<{
      slug: string;
      title: string;
      description: string;
      headline_stat: {
        total_affected_urls: number;
        errors: number;
        warnings: number;
        notices: number;
        total_urls_in_audit: number;
      } | null;
      sections: Array<{
        title: string;
        description: string;
        issues: Array<{
          slug: string;
          title: string;
          severity: string;
          category: string;
          why: string;
          how_to_fix: string;
          count: number;
        }>;
        notes: string[];
      }>;
      related_routes: Array<{ label: string; href: string }>;
    }>(`/themes/${encodeURIComponent(slug)}`),

  // Phase 4 — Near-duplicate URL clusters (MinHash + LSH).
  nearDuplicates: (params?: { n?: number; threshold?: number }) => {
    const qs = new URLSearchParams();
    if (params?.n !== undefined) qs.set('n', String(params.n));
    if (params?.threshold !== undefined) qs.set('threshold', String(params.threshold));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<{
      summary: {
        cluster_count: number;
        total_dupes: number;
        largest_cluster_size: number;
        largest_cluster_title: string;
        threshold: number;
      };
      clusters: Array<{
        cluster_id: number;
        cluster_size: number;
        representative_title: string;
        member_urls: string[];
        more_members: number;
      }>;
    }>(`/near-duplicates${suffix}`);
  },

  // Phase 6 — GEO suite (llms.txt + IndexNow + AI-bot logs + backlinks).
  llmsTxtAudit: (domain?: string) => {
    const qs = domain ? `?domain=${encodeURIComponent(domain)}` : '';
    return request<{
      domain: string;
      url: string;
      found: boolean;
      status_code: number;
      byte_size: number;
      section_count: number;
      link_count: number;
      has_h1: boolean;
      has_blockquote_summary: boolean;
      has_full_txt: boolean;
      full_txt_byte_size: number;
      issues: string[];
      raw_excerpt: string;
    }>(`/geo/llms-txt${qs}`);
  },
  llmsTxtDraft: (maxPagesPerSection?: number) => {
    const qs = maxPagesPerSection
      ? `?max_pages_per_section=${maxPagesPerSection}`
      : '';
    return request<{
      domain: string;
      body: string;
      page_count: number;
      section_count: number;
      char_count: number;
    }>(`/geo/llms-txt/draft${qs}`);
  },
  indexNowPing: (urls: string[]) =>
    request<{
      ok: boolean;
      submitted?: number;
      would_submit?: number;
      would_submit_sample?: string[];
      dry_run?: boolean;
      note?: string;
      status_code?: number;
      response_body?: string;
      rejected?: string[];
      rejected_count?: number;
      error?: string;
    }>('/geo/indexnow/ping', {
      method: 'POST',
      body: JSON.stringify({ urls }),
    }),
  aiBotHits: (limit?: number) => {
    const qs = limit ? `?limit=${limit}` : '';
    return request<{
      totals: Record<string, { total: number; verified: number; spoofed: number }>;
      recent: Array<{
        id: string;
        seen_at: string | null;
        bot: string;
        remote_ip: string | null;
        verified: boolean;
        url: string;
        status_code: number;
        bytes_sent: number;
        user_agent: string;
      }>;
    }>(`/geo/ai-bots${qs}`);
  },
  backlinks: (limit?: number) => {
    const qs = limit ? `?limit=${limit}` : '';
    return request<{
      summary: {
        total: number;
        per_target_domain: Array<{ target_domain: string; count: number }>;
        top_referring_domains: Array<{ source_domain: string; count: number }>;
      };
      backlinks: Array<{
        id: string;
        source_url: string;
        source_domain: string;
        target_url: string;
        target_domain: string;
        anchor_text: string;
        rel: string;
        nofollow: boolean;
        discovered_in: string;
        first_seen: string | null;
        last_seen: string | null;
      }>;
    }>(`/geo/backlinks${qs}`);
  },
};
