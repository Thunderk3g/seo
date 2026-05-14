// GscPage — Google Search Console source-data dashboard.
//
// Renders the full GSC dataset behind `/api/v1/seo/gsc/`:
//   - top-line KPIs (clicks / impressions / CTR / avg position)
//   - daily clicks-vs-impressions trend (last 90 days)
//   - top queries table by clicks
//   - top pages table by clicks
//   - underperforming queries (visible but not earning clicks)
//   - high-impression / low-click queries
//
// All numbers come from the CSVs pulled by `backend/scripts/gsc_pull.py`.
// When the snapshot is missing the page shows a clear "no data" state
// rather than throwing.

import { useState } from 'react';
import PerformanceChart from '../components/seo/PerformanceChart';
import { useGscDashboard } from '../api/hooks/useGscDashboard';
import type { GSCDashboard, GSCPageRow, GSCQueryRow } from '../api/seoTypes';

const PAGE_SIZE = 25;

export default function GscPage() {
  const { data, isLoading, isError } = useGscDashboard(200);

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Search Console</h1>
          <div className="seo-page-sub">
            Clicks, impressions, CTR and position from Google Search Console
            for <b>bajajlifeinsurance.com</b>.
          </div>
        </div>
      </header>

      {isLoading && <div className="seo-empty">Loading GSC data…</div>}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server is
          running on /api/v1/seo/.
        </div>
      )}

      {data && !data.available && (
        <div className="seo-empty">
          No Search Console data available.{' '}
          {data.error ? <span>({data.error})</span> : null} Run{' '}
          <b>backend/scripts/gsc_pull.py</b> to populate.
        </div>
      )}

      {data && data.available && <GscBody data={data} />}
    </div>
  );
}

function GscBody({ data }: { data: GSCDashboard }) {
  const t = data.totals!;
  return (
    <>
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Search performance</h2>
          <span className="seo-card-sub">
            Last {data.daily_series?.length ?? 0} days · Search Console
          </span>
        </div>
        <div className="seo-perf-totals">
          <Kpi label="Clicks" value={compact(t.clicks)} swatch="var(--accent)" />
          <Kpi
            label="Impressions"
            value={compact(t.impressions)}
            swatch="var(--text-2)"
          />
          <Kpi label="Avg CTR" value={`${(t.avg_ctr * 100).toFixed(2)}%`} />
          <Kpi label="Avg Position" value={t.avg_position.toFixed(1)} />
          <Kpi label="Queries" value={compact(t.queries)} />
          <Kpi label="Pages" value={compact(t.pages)} />
        </div>
        <PerformanceChart data={data.daily_series ?? []} />
      </div>

      <div className="seo-row-2-balanced">
        <QueryTable
          title="Top queries"
          subtitle="by clicks"
          rows={data.top_queries ?? []}
        />
        <PageTable
          title="Top pages"
          subtitle="by clicks"
          rows={data.top_pages ?? []}
        />
      </div>

      <div className="seo-row-2-balanced">
        <QueryTable
          title="Underperforming queries"
          subtitle="position 4–15 with below-curve CTR"
          rows={data.underperforming_queries ?? []}
        />
        <QueryTable
          title="High impressions, low clicks"
          subtitle="title/meta optimisation candidates"
          rows={data.high_impression_low_click_queries ?? []}
        />
      </div>
    </>
  );
}

function Kpi({
  label,
  value,
  swatch,
}: {
  label: string;
  value: string;
  swatch?: string;
}) {
  return (
    <div className="seo-perf-total">
      <span className="label">
        {swatch && <span className="swatch" style={{ background: swatch }} />}
        {label}
      </span>
      <span className="value">{value}</span>
    </div>
  );
}

function QueryTable({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle?: string;
  rows: GSCQueryRow[];
}) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>{title}</h2>
        {subtitle && <span className="seo-card-sub">{subtitle}</span>}
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Query</th>
                <th className="num">Clicks</th>
                <th className="num">Impr.</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr key={r.query}>
                  <td className="seo-cell-query" title={r.query}>
                    {r.query}
                  </td>
                  <td className="num">{r.clicks.toLocaleString()}</td>
                  <td className="num">{compact(r.impressions)}</td>
                  <td className="num">{(r.ctr * 100).toFixed(1)}%</td>
                  <td className="num">{r.position.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <Pager page={page} pages={pages} onChange={setPage} total={rows.length} />
          )}
        </>
      )}
    </div>
  );
}

function PageTable({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle?: string;
  rows: GSCPageRow[];
}) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>{title}</h2>
        {subtitle && <span className="seo-card-sub">{subtitle}</span>}
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Page</th>
                <th className="num">Clicks</th>
                <th className="num">Impr.</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr key={r.page}>
                  <td className="seo-cell-query" title={r.page}>
                    <a href={r.page} target="_blank" rel="noreferrer">
                      {shortPath(r.page)}
                    </a>
                  </td>
                  <td className="num">{r.clicks.toLocaleString()}</td>
                  <td className="num">{compact(r.impressions)}</td>
                  <td className="num">{(r.ctr * 100).toFixed(1)}%</td>
                  <td className="num">{r.position.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <Pager page={page} pages={pages} onChange={setPage} total={rows.length} />
          )}
        </>
      )}
    </div>
  );
}

function Pager({
  page,
  pages,
  onChange,
  total,
}: {
  page: number;
  pages: number;
  onChange: (p: number) => void;
  total: number;
}) {
  return (
    <div className="seo-pager">
      <button
        className="seo-btn seo-btn-ghost"
        onClick={() => onChange(Math.max(0, page - 1))}
        disabled={page === 0}
      >
        ‹ Prev
      </button>
      <span className="seo-pager-meta">
        Page {page + 1} of {pages} · {total.toLocaleString()} rows
      </span>
      <button
        className="seo-btn seo-btn-ghost"
        onClick={() => onChange(Math.min(pages - 1, page + 1))}
        disabled={page >= pages - 1}
      >
        Next ›
      </button>
    </div>
  );
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function shortPath(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname || '/';
  } catch {
    return url;
  }
}
