// UrlMiniTable — compact tabbed URL preview for the dashboard.
//
// Mirrors `.design-ref/project/dashboard.jsx` UrlMiniTable (lines
// 242-289). Tabs are All / Errors (4xx+5xx) / Redirects (3xx) / Slow
// (load_time_ms > 1000). Filters apply client-side over the first page
// of results from `usePages` — the dashboard mini-view does NOT paginate
// or hit a new query param.

import { useState } from 'react';
import { usePages } from '../../api/hooks/usePages';
import Icon from '../icons/Icon';
import type { PageListItem } from '../../api/types';

interface Props {
  sessionId: string | null;
}

type TabId = 'all' | 'errors' | 'redirects' | 'slow';

const SLOW_THRESHOLD_MS = 1000;

function statusClassNumber(code: number): number {
  return Math.floor(code / 100);
}

function filterRows(rows: PageListItem[], tab: TabId): PageListItem[] {
  if (tab === 'all') return rows;
  if (tab === 'errors') {
    return rows.filter((r) => {
      const cls = statusClassNumber(r.http_status_code);
      return cls === 4 || cls === 5;
    });
  }
  if (tab === 'redirects') {
    return rows.filter((r) => statusClassNumber(r.http_status_code) === 3);
  }
  if (tab === 'slow') {
    return rows.filter((r) => (r.load_time_ms ?? 0) > SLOW_THRESHOLD_MS);
  }
  return rows;
}

function shortPath(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname + (u.search || '');
  } catch {
    return url;
  }
}

export default function UrlMiniTable({ sessionId }: Props) {
  const [tab, setTab] = useState<TabId>('all');
  // Pull a single page; client-side filters reduce it. Page size 50 is
  // enough headroom for the mini-view's 10-row preview across all tabs.
  const pages = usePages({ sessionId, page: 1, pageSize: 50 });
  const rows = pages.data?.results ?? [];

  const counts = {
    all: rows.length,
    errors: filterRows(rows, 'errors').length,
    redirects: filterRows(rows, 'redirects').length,
    slow: filterRows(rows, 'slow').length,
  };

  const tabs: { id: TabId; label: string; count: number }[] = [
    { id: 'all', label: 'All', count: counts.all },
    { id: 'errors', label: 'Errors', count: counts.errors },
    { id: 'redirects', label: 'Redirects', count: counts.redirects },
    { id: 'slow', label: 'Slow', count: counts.slow },
  ];

  const filtered = filterRows(rows, tab).slice(0, 10);

  return (
    <div className="card url-mini">
      <div className="card-head">
        <div className="tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={'tab ' + (t.id === tab ? 'active' : '')}
              onClick={() => setTab(t.id)}
              type="button"
            >
              {t.label}{' '}
              <span className="tab-count">{t.count.toLocaleString()}</span>
            </button>
          ))}
        </div>
        <a className="link-btn" href="#pages">
          Open table <Icon name="external" size={11} />
        </a>
      </div>

      {!sessionId && (
        <p className="text-muted" style={{ fontSize: 12 }}>
          No crawl session yet.
        </p>
      )}
      {sessionId && pages.isPending && (
        <p className="text-muted" style={{ fontSize: 12 }}>Loading…</p>
      )}
      {sessionId && pages.isError && (
        <p style={{ color: '#f87171', fontSize: 12 }}>
          Failed to load pages.
        </p>
      )}

      {sessionId && pages.data && (
        <div className="url-table">
          <div className="url-table-head">
            <div>URL</div>
            <div>Status</div>
            <div>Title</div>
            <div className="num">Resp</div>
            <div className="num">Depth</div>
          </div>
          {filtered.length === 0 && (
            <p
              className="text-muted"
              style={{ fontSize: 12, padding: '12px 6px' }}
            >
              No URLs match this filter.
            </p>
          )}
          {filtered.map((u) => (
            <div key={u.id} className="url-row">
              <div className="url-cell" title={u.url}>
                {shortPath(u.url)}
              </div>
              <div>
                <span
                  className={
                    'status-pill s' + statusClassNumber(u.http_status_code)
                  }
                >
                  {u.http_status_code}
                </span>
              </div>
              <div className="title-cell" title={u.title ?? ''}>
                {u.title || (
                  <span className="text-muted-i">— missing —</span>
                )}
              </div>
              <div className="num">
                {Math.round(u.load_time_ms)}
                <span className="text-muted">ms</span>
              </div>
              <div className="num">{u.crawl_depth}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
