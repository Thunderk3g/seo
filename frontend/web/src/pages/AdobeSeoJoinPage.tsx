// AdobeSeoJoinPage — cross-source view.
//
// One row per Adobe top-page, joined with the latest Bajaj crawl
// snapshot (CrawlerPageResult) + GSC export (web__page.csv). Surfaces:
//
//   * "High impression, low actual traffic" — GSC says we're ranking
//     but Adobe says nobody's clicking.
//   * Pages in Adobe traffic but missing from crawl (sitemap gap).
//   * Pages with crawl errors (4xx/5xx) still receiving traffic.
//
// Filters: search box + a "high impression / low traffic" toggle.

import { useMemo, useState } from 'react';
import {
  useAdobeSeoJoin,
  type AdobeSeoJoinRow,
} from '../api/hooks/useAdobeDashboard';

const LOOKBACK_OPTIONS = [7, 14, 30, 60, 90];
const LIMIT_OPTIONS = [50, 100, 200, 500];

type SortKey =
  | 'page'
  | 'page_views'
  | 'visits'
  | 'gsc_impressions'
  | 'gsc_clicks'
  | 'gsc_position';

export default function AdobeSeoJoinPage() {
  const [lookback, setLookback] = useState(30);
  const [limit, setLimit] = useState(100);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'highimp' | 'errors' | 'no_crawl'>(
    'all',
  );
  const [sortKey, setSortKey] = useState<SortKey>('page_views');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const { data, isLoading, isError } = useAdobeSeoJoin(lookback, limit);

  const filteredRows = useMemo(() => {
    const rows = data?.rows ?? [];
    const q = search.trim().toLowerCase();
    return rows
      .filter((r) => {
        if (q && !r.page.toLowerCase().includes(q) && !r.url.toLowerCase().includes(q))
          return false;
        switch (filter) {
          case 'highimp':
            return (r.gsc_impressions ?? 0) > 1000 && r.visits < 50;
          case 'errors':
            return r.has_any_error;
          case 'no_crawl':
            return !r.in_crawl;
          default:
            return true;
        }
      })
      .sort((a, b) => {
        const av = a[sortKey] ?? 0;
        const bv = b[sortKey] ?? 0;
        if (av < bv) return sortDir === 'asc' ? -1 : 1;
        if (av > bv) return sortDir === 'asc' ? 1 : -1;
        return 0;
      });
  }, [data?.rows, search, filter, sortKey, sortDir]);

  const totals = data?.totals;

  const setSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k);
      setSortDir(k === 'page' ? 'asc' : 'desc');
    }
  };

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>SEO × Adobe</h1>
          <div className="seo-page-sub">
            Adobe top pages joined with the latest Bajaj crawl snapshot and
            the GSC web · page export. The fix-list view.
          </div>
        </div>
        <div className="seo-page-controls">
          <label className="seo-control">
            <span>Lookback</span>
            <select
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value))}
            >
              {LOOKBACK_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </select>
          </label>
          <label className="seo-control">
            <span>Top-N from Adobe</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {isLoading && (
        <div className="seo-empty">Building the SEO × Adobe join…</div>
      )}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend at /api/v1/seo/adobe/seo-join/.
        </div>
      )}

      {data && !data.available && (
        <div className="seo-empty">
          {data.reason === 'not_configured' ? (
            <>Configure Adobe Analytics first (see the Adobe Analytics page).</>
          ) : (
            <>The join could not run: {data.error}</>
          )}
        </div>
      )}

      {data && data.available && (
        <>
          {/* KPI strip */}
          <div className="seo-card seo-perf-card">
            <div className="seo-card-head">
              <h2>Join summary</h2>
              <span className="seo-card-sub">
                Adobe lookback {data.lookback_days ?? lookback} days ·{' '}
                {totals?.rows ?? 0} pages
              </span>
            </div>
            <div className="seo-perf-totals">
              <Kpi label="Pages joined" value={totals?.rows} />
              <Kpi label="In crawl" value={totals?.in_crawl} />
              <Kpi label="With GSC data" value={totals?.with_gsc} />
              <Kpi label="With crawl errors" value={totals?.with_errors} />
              <Kpi
                label="High impr · low traffic"
                value={totals?.high_impression_no_traffic}
              />
            </div>
          </div>

          {/* Filter strip */}
          <div className="seo-card">
            <div
              className="seo-card-head"
              style={{ alignItems: 'center', gap: 12 }}
            >
              <h2 style={{ flex: 1 }}>Pages</h2>
              <input
                className="seo-search"
                placeholder="Filter by URL / page slug"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="seo-tabs" style={{ flexShrink: 0 }}>
                <FilterPill
                  active={filter === 'all'}
                  onClick={() => setFilter('all')}
                  label="All"
                />
                <FilterPill
                  active={filter === 'highimp'}
                  onClick={() => setFilter('highimp')}
                  label="High impr · low traffic"
                />
                <FilterPill
                  active={filter === 'errors'}
                  onClick={() => setFilter('errors')}
                  label="Crawl errors"
                />
                <FilterPill
                  active={filter === 'no_crawl'}
                  onClick={() => setFilter('no_crawl')}
                  label="Not in crawl"
                />
              </div>
            </div>
            <JoinTable
              rows={filteredRows}
              sortKey={sortKey}
              sortDir={sortDir}
              setSort={setSort}
            />
          </div>
        </>
      )}
    </div>
  );
}

function JoinTable({
  rows,
  sortKey,
  sortDir,
  setSort,
}: {
  rows: AdobeSeoJoinRow[];
  sortKey: SortKey;
  sortDir: 'asc' | 'desc';
  setSort: (k: SortKey) => void;
}) {
  if (rows.length === 0) {
    return (
      <div className="seo-empty">No rows match the current filter.</div>
    );
  }
  const arrow = (k: SortKey) =>
    sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
  return (
    <div className="seo-table-scroll">
      <table className="seo-table">
        <thead>
          <tr>
            <th onClick={() => setSort('page')} style={{ cursor: 'pointer' }}>
              Page / URL{arrow('page')}
            </th>
            <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => setSort('page_views')}>
              Adobe views{arrow('page_views')}
            </th>
            <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => setSort('visits')}>
              Adobe visits{arrow('visits')}
            </th>
            <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => setSort('gsc_impressions')}>
              GSC impr.{arrow('gsc_impressions')}
            </th>
            <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => setSort('gsc_clicks')}>
              GSC clicks{arrow('gsc_clicks')}
            </th>
            <th style={{ textAlign: 'right', cursor: 'pointer' }} onClick={() => setSort('gsc_position')}>
              Avg pos.{arrow('gsc_position')}
            </th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.page}-${i}`}>
              <td>
                <div className="seo-cell-page">{r.page || <i>(unset)</i>}</div>
                <div className="seo-cell-url" title={r.url}>
                  {r.url}
                </div>
              </td>
              <td className="seo-num">{r.page_views.toLocaleString()}</td>
              <td className="seo-num">{r.visits.toLocaleString()}</td>
              <td className="seo-num">
                {r.gsc_impressions !== null
                  ? r.gsc_impressions.toLocaleString()
                  : '—'}
              </td>
              <td className="seo-num">
                {r.gsc_clicks !== null
                  ? r.gsc_clicks.toLocaleString()
                  : '—'}
              </td>
              <td className="seo-num">
                {r.gsc_position !== null ? r.gsc_position.toFixed(1) : '—'}
              </td>
              <td>
                <StatusBadges row={r} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadges({ row }: { row: AdobeSeoJoinRow }) {
  return (
    <div className="seo-badges">
      {row.in_crawl ? (
        <span className={`seo-badge ${row.has_any_error ? 'seo-badge-err' : 'seo-badge-ok'}`}>
          {row.status_code || 'crawled'}
        </span>
      ) : (
        <span className="seo-badge seo-badge-warn">no crawl</span>
      )}
      {row.indexed_status === 'indexed' && (
        <span className="seo-badge seo-badge-ok">indexed</span>
      )}
      {row.indexed_status === 'not_indexed' && (
        <span className="seo-badge seo-badge-warn">not indexed</span>
      )}
      {row.indexed_status === 'excluded' && (
        <span className="seo-badge seo-badge-err">excluded</span>
      )}
      {row.from_sitemap && (
        <span className="seo-badge seo-badge-neutral">sitemap</span>
      )}
    </div>
  );
}

function FilterPill({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className={`seo-tab ${active ? 'active' : ''}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function Kpi({
  label,
  value,
}: {
  label: string;
  value: number | string | null | undefined;
}) {
  return (
    <div className="seo-kpi">
      <div className="seo-kpi-label">{label}</div>
      <div className="seo-kpi-value">
        {value === null || value === undefined ? '—' : value.toLocaleString()}
      </div>
    </div>
  );
}
