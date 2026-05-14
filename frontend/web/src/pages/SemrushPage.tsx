// SemrushPage — organic keyword rankings dashboard.
//
// Pulls from `/api/v1/seo/semrush/?domain=...&limit=...`, which wraps
// the `domain_ranks` + `domain_organic` SEMrush endpoints. Server-side
// results are cached on disk for 24h so paging or re-renders don't
// burn billable units.
//
// Sections:
//   - KPI strip from `domain_ranks` (organic kw count, traffic, cost)
//   - sortable / searchable keyword table from `domain_organic`
//   - small movers panel (biggest position gains vs previous_position)

import { useMemo, useState } from 'react';
import { useSemrushDashboard } from '../api/hooks/useSemrushDashboard';
import type { SemrushDashboard, SemrushKeywordRow } from '../api/seoTypes';

const PAGE_SIZE = 25;

type SortKey =
  | 'keyword'
  | 'position'
  | 'previous_position'
  | 'search_volume'
  | 'traffic_pct'
  | 'cpc'
  | 'competition';

export default function SemrushPage() {
  const { data, isLoading, isError } = useSemrushDashboard();

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>SEMrush Keywords</h1>
          <div className="seo-page-sub">
            Organic search visibility and keyword rankings for{' '}
            <b>{data?.domain ?? 'bajajlifeinsurance.com'}</b>
            {data?.database ? ` · ${data.database.toUpperCase()} database` : ''}.
          </div>
        </div>
      </header>

      {isLoading && <div className="seo-empty">Loading SEMrush data…</div>}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server is
          running on /api/v1/seo/.
        </div>
      )}

      {data && !data.available && (
        <div className="seo-empty">
          SEMrush is not configured.{' '}
          {data.error ? <span>({data.error})</span> : null} Set{' '}
          <b>SEMRUSH_API_KEY</b> in the backend environment to enable this
          page.
        </div>
      )}

      {data && data.available && <SemrushBody data={data} />}
    </div>
  );
}

function SemrushBody({ data }: { data: SemrushDashboard }) {
  const o = data.overview!;
  const keywords = data.keywords ?? [];
  return (
    <>
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Domain overview</h2>
          <span className="seo-card-sub">SEMrush · {data.database?.toUpperCase()}</span>
        </div>
        <div className="seo-perf-totals">
          <Kpi label="Organic keywords" value={compact(o.organic_keywords)} />
          <Kpi label="Organic traffic" value={compact(o.organic_traffic)} />
          <Kpi
            label="Organic traffic cost"
            value={`$${compact(o.organic_cost)}`}
          />
          <Kpi label="SEMrush rank" value={o.rank.toLocaleString()} />
          <Kpi label="Adwords keywords" value={compact(o.adwords_keywords)} />
          <Kpi label="Adwords traffic" value={compact(o.adwords_traffic)} />
        </div>
      </div>

      <div className="seo-row-2-balanced">
        <MoversCard rows={keywords} direction="up" />
        <MoversCard rows={keywords} direction="down" />
      </div>

      <KeywordTable rows={keywords} />
    </>
  );
}

function KeywordTable({ rows }: { rows: SemrushKeywordRow[] }) {
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('traffic_pct');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const base = q ? rows.filter((r) => r.keyword.toLowerCase().includes(q)) : rows;
    const sorted = [...base].sort((a, b) => {
      const av = a[sortKey] as number | string;
      const bv = b[sortKey] as number | string;
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const an = Number(av);
      const bn = Number(bv);
      return sortDir === 'asc' ? an - bn : bn - an;
    });
    return sorted;
  }, [rows, filter, sortKey, sortDir]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const slice = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  function header(label: string, key: SortKey, numeric = false) {
    const active = sortKey === key;
    return (
      <th
        className={numeric ? 'num seo-sortable' : 'seo-sortable'}
        onClick={() => {
          if (active) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
          else {
            setSortKey(key);
            setSortDir(numeric ? 'desc' : 'asc');
          }
          setPage(0);
        }}
      >
        {label}
        {active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
      </th>
    );
  }

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Organic keywords</h2>
        <span className="seo-card-sub">
          {filtered.length.toLocaleString()} of {rows.length.toLocaleString()}{' '}
          rows
        </span>
      </div>
      <div className="seo-toolbar">
        <input
          type="search"
          className="seo-input"
          placeholder="Filter keywords…"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        />
      </div>
      {filtered.length === 0 ? (
        <div className="seo-empty">No keywords match.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                {header('Keyword', 'keyword')}
                {header('Pos', 'position', true)}
                {header('Prev', 'previous_position', true)}
                {header('Volume', 'search_volume', true)}
                {header('Traffic %', 'traffic_pct', true)}
                {header('CPC', 'cpc', true)}
                {header('Comp.', 'competition', true)}
                <th>URL</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => {
                const delta = r.previous_position
                  ? r.previous_position - r.position
                  : 0;
                return (
                  <tr key={`${r.keyword}-${r.url}`}>
                    <td className="seo-cell-query" title={r.keyword}>
                      {r.keyword}
                    </td>
                    <td className="num">{r.position || '—'}</td>
                    <td className={`num ${moverClass(delta)}`}>
                      {r.previous_position
                        ? `${r.previous_position}${delta ? ` (${delta > 0 ? '+' : ''}${delta})` : ''}`
                        : 'new'}
                    </td>
                    <td className="num">{r.search_volume.toLocaleString()}</td>
                    <td className="num">{r.traffic_pct.toFixed(2)}%</td>
                    <td className="num">${r.cpc.toFixed(2)}</td>
                    <td className="num">{r.competition.toFixed(2)}</td>
                    <td className="seo-cell-query" title={r.url}>
                      <a href={r.url} target="_blank" rel="noreferrer">
                        {shortPath(r.url)}
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {pages > 1 && (
            <div className="seo-pager">
              <button
                className="seo-btn seo-btn-ghost"
                onClick={() => setPage(Math.max(0, safePage - 1))}
                disabled={safePage === 0}
              >
                ‹ Prev
              </button>
              <span className="seo-pager-meta">
                Page {safePage + 1} of {pages}
              </span>
              <button
                className="seo-btn seo-btn-ghost"
                onClick={() => setPage(Math.min(pages - 1, safePage + 1))}
                disabled={safePage >= pages - 1}
              >
                Next ›
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MoversCard({
  rows,
  direction,
}: {
  rows: SemrushKeywordRow[];
  direction: 'up' | 'down';
}) {
  const movers = useMemo(() => {
    const filtered = rows
      .filter((r) => r.previous_position > 0 && r.position > 0)
      .map((r) => ({ ...r, delta: r.previous_position - r.position }));
    const dirMovers =
      direction === 'up'
        ? filtered.filter((r) => r.delta > 0).sort((a, b) => b.delta - a.delta)
        : filtered.filter((r) => r.delta < 0).sort((a, b) => a.delta - b.delta);
    return dirMovers.slice(0, 10);
  }, [rows, direction]);

  const title = direction === 'up' ? 'Biggest gainers' : 'Biggest losers';
  const sub =
    direction === 'up'
      ? 'positions improved vs previous period'
      : 'positions dropped vs previous period';

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>{title}</h2>
        <span className="seo-card-sub">{sub}</span>
      </div>
      {movers.length === 0 ? (
        <div className="seo-empty">No movement data.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Keyword</th>
              <th className="num">Now</th>
              <th className="num">Was</th>
              <th className="num">Δ</th>
            </tr>
          </thead>
          <tbody>
            {movers.map((r) => (
              <tr key={`${r.keyword}-${r.url}`}>
                <td className="seo-cell-query" title={r.keyword}>
                  {r.keyword}
                </td>
                <td className="num">{r.position}</td>
                <td className="num">{r.previous_position}</td>
                <td className={`num ${moverClass(r.delta)}`}>
                  {r.delta > 0 ? `+${r.delta}` : r.delta}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="seo-perf-total">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

function moverClass(delta: number): string {
  if (delta > 0) return 'seo-mover-up';
  if (delta < 0) return 'seo-mover-down';
  return '';
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
