// PagesUrlsPage — Pages/URLs screen for the active site's latest session.
//
// Layout ported from .design-ref/project/pages.jsx (PagesPage component):
//   PageHeader • tabs (All/HTML/Images/4xx/3xx/5xx) • search + status select
//   • sortable paginated table.
//
// Behaviour cuts (per spec §5.4.3): "Advanced filters" and "Export CSV"
// buttons are omitted in v1 — Export lands on Day 4. "Re-crawl" is wired to
// the existing useStartCrawl mutation.
//
// Tab counts: only the "All" tab shows a count (the total from the current
// paginated response). Status/content-type bucket counts are intentionally
// omitted — the backend doesn't expose per-bucket counts and we don't want
// to fabricate them. See spec note on this file's brief.

import { useState } from 'react';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import {
  usePages,
  type ContentTypeBucket,
  type StatusClass,
} from '../api/hooks/usePages';
import { useStartCrawl } from '../api/hooks/useStartCrawl';
import PageHeader from '../components/PageHeader';
import Icon from '../components/icons/Icon';
import PagesTable from '../components/tables/PagesTable';

const TABS: { id: ContentTypeBucket | StatusClass; label: string; kind: 'content' | 'status' }[] = [
  { id: '', label: 'All', kind: 'content' },
  { id: 'html', label: 'HTML', kind: 'content' },
  { id: 'image', label: 'Images', kind: 'content' },
  { id: '4xx', label: '4xx', kind: 'status' },
  { id: '3xx', label: '3xx', kind: 'status' },
  { id: '5xx', label: '5xx', kind: 'status' },
];

const PAGE_SIZE = 50;

export default function PagesUrlsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Use the most recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;

  const [activeTab, setActiveTab] = useState<string>(''); // '' = All
  const [statusClass, setStatusClass] = useState<StatusClass>('');
  const [contentType, setContentType] = useState<ContentTypeBucket>('');
  const [q, setQ] = useState('');
  const [ordering, setOrdering] = useState('crawl_depth');
  const [page, setPage] = useState(1);

  const startCrawl = useStartCrawl();

  function handleTab(tabId: string, kind: 'content' | 'status') {
    setActiveTab(tabId);
    setPage(1);
    if (kind === 'content') {
      setContentType(tabId as ContentTypeBucket);
      setStatusClass('');
    } else {
      setStatusClass(tabId as StatusClass);
      setContentType('');
    }
  }

  const pagesQuery = usePages({
    sessionId: session?.id ?? null,
    page,
    pageSize: PAGE_SIZE,
    statusClass,
    contentType,
    q,
    ordering,
  });

  // Total count across the active filter — used to badge the "All" tab.
  const totalCount = pagesQuery.data?.count ?? null;

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (!session) return 'No crawl sessions yet — start one from the topbar';
    return `Latest session: ${session.website_domain} • ${session.status}`;
  })();

  return (
    <div className="page-grid">
      <PageHeader
        title="Pages / URLs"
        subtitle={subtitle}
        actions={
          <button
            type="button"
            className="btn primary"
            disabled={!activeSiteId || startCrawl.isPending}
            onClick={() => activeSiteId && startCrawl.mutate(activeSiteId)}
            title={
              activeSiteId ? 'Start a fresh crawl on the active site' : 'No active site'
            }
          >
            <span>{startCrawl.isPending ? 'Starting…' : 'Re-crawl'}</span>
          </button>
        }
      />

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to see crawled pages.
          </p>
        </div>
      )}

      {activeSiteId && !session && !sessionsQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No crawl sessions exist for this site yet. Click <strong>Re-crawl</strong>{' '}
            above to start one.
          </p>
        </div>
      )}

      {session && (
        <div className="card big-table">
          <div className="card-head card-head-flex">
            <div className="tabs">
              {TABS.map((t) => {
                const isAll = t.id === '' && t.kind === 'content';
                const showCount = isAll && totalCount !== null;
                return (
                  <button
                    key={t.label}
                    type="button"
                    className={'tab ' + (t.id === activeTab ? 'active' : '')}
                    onClick={() => handleTab(t.id, t.kind)}
                  >
                    {t.label}
                    {showCount && (
                      <>
                        {' '}
                        <span className="tab-count">
                          {totalCount.toLocaleString()}
                        </span>
                      </>
                    )}
                  </button>
                );
              })}
            </div>
            <div className="table-toolbar">
              <div className="search-field small">
                <Icon name="search" size={13} />
                <input
                  type="text"
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    setPage(1);
                  }}
                  placeholder="Search URL or title…"
                />
              </div>
              <select
                className="select-field"
                value={statusClass || 'all'}
                onChange={(e) => {
                  const v = e.target.value;
                  setStatusClass(v === 'all' ? '' : (v as StatusClass));
                  setPage(1);
                  // Clear tab selection if it was a status tab to avoid double-filter.
                  if (TABS.find((t) => t.id === activeTab)?.kind === 'status') {
                    setActiveTab('');
                  }
                }}
              >
                <option value="all">Any status</option>
                <option value="2xx">2xx</option>
                <option value="3xx">3xx</option>
                <option value="4xx">4xx</option>
                <option value="5xx">5xx</option>
              </select>
            </div>
          </div>

          {pagesQuery.isError && (
            <div style={{ padding: 14, color: 'var(--error, #f87171)' }}>
              Failed to load pages
              {pagesQuery.error instanceof Error
                ? `: ${pagesQuery.error.message}`
                : '.'}
            </div>
          )}

          <PagesTable
            data={pagesQuery.data}
            isLoading={pagesQuery.isPending || pagesQuery.isFetching}
            page={page}
            pageSize={PAGE_SIZE}
            ordering={ordering}
            onPageChange={setPage}
            onOrderingChange={(next) => {
              setOrdering(next);
              setPage(1);
            }}
          />
        </div>
      )}
    </div>
  );
}
