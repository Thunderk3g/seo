// PagesTable.tsx — paginated/sortable table for the Pages/URLs screen.
//
// Lifts the design-ref `.big-table` / `.bt-row` styles. The 10-column design
// grid is replaced with a 7-column layout because PageListSerializer doesn't
// expose meta_description / inlinks / outlinks / size_kb. lattice.css is
// read-only per Day-0 contract — overrides happen inline.
//
// Per-row data lives in the parent's `usePages()` query; this component is
// presentational and emits sort + page change callbacks.

import type { PageListItem, PaginatedResponse } from '../../api/types';

interface PagesTableProps {
  data: PaginatedResponse<PageListItem> | undefined;
  isLoading: boolean;
  page: number;
  pageSize: number;
  ordering: string;
  onPageChange: (next: number) => void;
  onOrderingChange: (next: string) => void;
}

// 7 columns: # | URL | Status | Title | Depth | Resp | Words
// Fixed-width numerics on the right; URL + Title get fr units for ellipsing.
const GRID_COLUMNS = '36px 2fr 70px 1.6fr 60px 80px 70px';

const SORT_FIELDS = {
  url: { asc: 'url', desc: '-url' },
  title: { asc: 'title', desc: '-title' },
  status: { asc: 'http_status_code', desc: '-http_status_code' },
  depth: { asc: 'crawl_depth', desc: '-crawl_depth' },
  resp: { asc: 'load_time_ms', desc: '-load_time_ms' },
  words: { asc: 'word_count', desc: '-word_count' },
} as const;

type SortField = keyof typeof SORT_FIELDS;

function statusClassFor(code: number | null): string {
  if (code === null || code === undefined) return 's0';
  return `s${Math.floor(code / 100)}`;
}

function sortIconFor(field: SortField, ordering: string): string {
  const { asc, desc } = SORT_FIELDS[field];
  if (ordering === asc) return ' ↑';
  if (ordering === desc) return ' ↓';
  return '';
}

function nextOrderingFor(field: SortField, ordering: string): string {
  const { asc, desc } = SORT_FIELDS[field];
  if (ordering === asc) return desc;
  if (ordering === desc) return ''; // third click clears sort
  return asc;
}

export default function PagesTable({
  data,
  isLoading,
  page,
  pageSize,
  ordering,
  onPageChange,
  onOrderingChange,
}: PagesTableProps) {
  const rows = data?.results ?? [];
  const total = data?.count ?? 0;
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1;
  const firstRowIdx = (page - 1) * pageSize + 1;
  const lastRowIdx = Math.min(page * pageSize, total);

  function HeaderCell({
    field, label, align = 'left',
  }: { field: SortField; label: string; align?: 'left' | 'right' }) {
    return (
      <div
        onClick={() => onOrderingChange(nextOrderingFor(field, ordering))}
        style={{ textAlign: align, justifyContent: align === 'right' ? 'flex-end' : 'flex-start' }}
        title={`Sort by ${label.toLowerCase()}`}
      >
        {label}
        {sortIconFor(field, ordering)}
      </div>
    );
  }

  return (
    <div className="big-url-table">
      <div className="bt-row bt-head" style={{ gridTemplateColumns: GRID_COLUMNS }}>
        <div className="bt-num">#</div>
        <HeaderCell field="url" label="URL" />
        <HeaderCell field="status" label="Status" />
        <HeaderCell field="title" label="Title" />
        <HeaderCell field="depth" label="Depth" align="right" />
        <HeaderCell field="resp" label="Resp" align="right" />
        <HeaderCell field="words" label="Words" align="right" />
      </div>

      {isLoading && rows.length === 0 && (
        <div className="bt-row" style={{ gridTemplateColumns: '1fr', padding: '20px 14px' }}>
          <div className="text-muted">Loading pages…</div>
        </div>
      )}

      {!isLoading && rows.length === 0 && (
        <div className="bt-row" style={{ gridTemplateColumns: '1fr', padding: '20px 14px' }}>
          <div className="text-muted">
            No pages match the current filter. Try changing the tab, status filter, or search.
          </div>
        </div>
      )}

      {rows.map((row, i) => (
        <div key={row.id} className="bt-row" style={{ gridTemplateColumns: GRID_COLUMNS }}>
          <div className="bt-num">{firstRowIdx + i}</div>
          <div className="bt-url">
            <span className="bt-url-link" title={row.url}>{row.url}</span>
          </div>
          <div>
            <span className={`status-pill ${statusClassFor(row.http_status_code)}`}>
              {row.http_status_code ?? '—'}
            </span>
          </div>
          <div className="bt-title" title={row.title || ''}>
            {row.title || <span className="text-muted-i">— missing —</span>}
          </div>
          <div className="bt-num2">{row.crawl_depth}</div>
          <div className="bt-num2">
            {row.load_time_ms != null
              ? <>{Math.round(row.load_time_ms)}<span className="text-muted">ms</span></>
              : '—'}
          </div>
          <div className="bt-num2">{row.word_count.toLocaleString()}</div>
        </div>
      ))}

      <div className="table-foot">
        <span className="text-muted">
          {total > 0
            ? `${firstRowIdx.toLocaleString()}–${lastRowIdx.toLocaleString()} of ${total.toLocaleString()}`
            : '0 results'}
        </span>
        <div className="pager">
          <button
            type="button"
            className="icon-btn"
            disabled={page <= 1 || isLoading}
            onClick={() => onPageChange(page - 1)}
            title="Previous page"
          >
            ‹
          </button>
          <span className="text-muted" style={{ padding: '0 8px' }}>
            page {page} / {totalPages}
          </span>
          <button
            type="button"
            className="icon-btn"
            disabled={page >= totalPages || isLoading}
            onClick={() => onPageChange(page + 1)}
            title="Next page"
          >
            ›
          </button>
        </div>
      </div>
    </div>
  );
}
