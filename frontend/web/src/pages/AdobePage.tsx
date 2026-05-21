// AdobePage — Adobe Analytics 2.0 dashboard (Bajaj Life Insurance).
//
// Pulls from `/api/v1/seo/adobe/?lookback=7&limit=25`. The backend
// authenticates server-to-server via Adobe IMS (client_credentials)
// and caches the 24-hour bearer token in memory, so re-renders are
// effectively free in normal use.
//
// Sections:
//   - Header w/ report-suite name + RSID + global company id
//   - KPI strip: total views (window), unique pages with traffic,
//     dimensions available, metrics available
//   - Top pages table (sortable by page-views or page name)
//
// Empty state (when ADOBE_* env vars are missing) prompts the operator
// to configure the credentials in `.env` and reload.

import { useMemo, useState } from 'react';
import {
  useAdobeDashboard,
  type AdobeDashboardResponse,
  type AdobeTopPageRow,
} from '../api/hooks/useAdobeDashboard';

const LOOKBACK_OPTIONS = [7, 14, 30];
const LIMIT_OPTIONS = [25, 50, 100];

type SortKey = 'page' | 'page_views';

export default function AdobePage() {
  const [lookback, setLookback] = useState<number>(7);
  const [limit, setLimit] = useState<number>(25);
  const { data, isLoading, isError } = useAdobeDashboard(lookback, limit);

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Adobe Analytics</h1>
          <div className="seo-page-sub">
            Behaviour and page performance for{' '}
            <b>
              {data?.report_suite?.name ||
                data?.rsid ||
                'bajajallianzbalicprod'}
            </b>
            {data?.global_company_id ? (
              <>
                {' '}· Company <code>{data.global_company_id}</code>
              </>
            ) : null}
            {data?.lookback_days
              ? ` · Last ${data.lookback_days} days`
              : null}
            .
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
            <span>Top pages</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {isLoading && (
        <div className="seo-empty">Loading Adobe Analytics data…</div>
      )}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server is
          running on /api/v1/seo/.
        </div>
      )}

      {data && !data.available && (
        <div className="seo-empty">
          Adobe Analytics is not configured.{' '}
          {data.reason === 'not_configured' ? (
            <>
              Set <b>ADOBE_CLIENT_ID</b>, <b>ADOBE_CLIENT_SECRET</b>,{' '}
              <b>ADOBE_GLOBAL_COMPANY_ID</b>, and <b>ADOBE_RSID</b> in the
              backend <code>.env</code> and reload.
            </>
          ) : (
            <span>{data.error}</span>
          )}
        </div>
      )}

      {data && data.available && <AdobeBody data={data} />}
    </div>
  );
}

function AdobeBody({ data }: { data: AdobeDashboardResponse }) {
  const totals = data.totals ?? {};
  const rows = data.top_pages ?? [];

  return (
    <>
      {/* KPI strip */}
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Window summary</h2>
          <span className="seo-card-sub">
            {data.report_suite?.rsid ?? data.rsid} · Last{' '}
            {data.lookback_days ?? '?'} days
          </span>
        </div>
        <div className="seo-perf-totals">
          <Kpi
            label="Total page-views"
            value={compact(totals.total_views)}
          />
          <Kpi
            label="Pages with traffic"
            value={compact(totals.total_pages)}
          />
          <Kpi
            label="Top-page views"
            value={compact(totals.col_max)}
          />
          <Kpi
            label="Dimensions"
            value={compact(data.dimension_count)}
          />
          <Kpi label="Metrics" value={compact(data.metric_count)} />
        </div>
      </div>

      {/* Top pages table */}
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Top pages by page-views</h2>
          <span className="seo-card-sub">
            Sorted by page-view count · {rows.length} rows
          </span>
        </div>
        {rows.length === 0 ? (
          <div className="seo-empty">
            No rows returned for this window. Widen the lookback or check
            that the report suite has traffic.
          </div>
        ) : (
          <TopPagesTable rows={rows} />
        )}
      </div>

      {/* Capability footer — useful sanity check that the API is
          surfacing the full Workspace surface. */}
      <div className="seo-card-foot">
        <span>
          {data.dimension_count ?? 0} dimensions · {data.metric_count ?? 0}{' '}
          metrics · report suite "{data.report_suite?.name ?? '?'}".
        </span>
      </div>
    </>
  );
}

function TopPagesTable({ rows }: { rows: AdobeTopPageRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('page_views');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = sortKey === 'page' ? a.page : a.page_views;
      const bv = sortKey === 'page' ? b.page : b.page_views;
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const setSort = (k: SortKey) => {
    if (sortKey === k) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(k);
      setSortDir(k === 'page' ? 'asc' : 'desc');
    }
  };

  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th
            onClick={() => setSort('page')}
            style={{ cursor: 'pointer' }}
          >
            Page{sortKey === 'page' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </th>
          <th
            onClick={() => setSort('page_views')}
            style={{ cursor: 'pointer', textAlign: 'right' }}
          >
            Page views
            {sortKey === 'page_views'
              ? sortDir === 'asc'
                ? ' ▲'
                : ' ▼'
              : ''}
          </th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r, idx) => (
          <tr key={r.item_id || `${r.page}-${idx}`}>
            <td className="seo-num">{idx + 1}</td>
            <td>{r.page || <i>(unset)</i>}</td>
            <td className="seo-num">{r.page_views.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Kpi({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="seo-kpi">
      <div className="seo-kpi-label">{label}</div>
      <div className="seo-kpi-value">{value ?? '—'}</div>
    </div>
  );
}

function compact(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (abs >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return Math.round(n).toLocaleString();
}
