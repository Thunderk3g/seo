// GscPage — Google Search Console source-data dashboard.
//
// Renders every CSV pulled by `backend/scripts/gsc_pull.py` (web +
// image + sitemaps + manual UI export). Strictly file-backed —
// nothing on this page issues a live GSC API call, so it keeps
// working while operator OAuth access is temporarily revoked.
//
// Seven tabs. Each tab is a focused SEO lens:
//
//   1. Overview      — headline KPIs, 90-day trend, branded ratio,
//                      data-on-disk inventory
//   2. Queries       — top, underperforming, high-imp-low-click,
//                      branded vs unbranded, top unbranded
//   3. Pages         — top pages, page × country, page × device
//   4. Geo           — country mix, query × country (NRI tail)
//   5. Devices       — mobile vs desktop split, query × device
//   6. Rich Results  — searchAppearance, sitemaps, indexation
//                      report (Crawled-not-indexed, 404s, etc.)
//   7. Image Search  — image queries / pages / geo / devices /
//                      daily — Bajaj actually ranks here
//
// Reuses the existing PerformanceChart + Pager components.

import { useMemo, useState } from 'react';
import PerformanceChart from '../components/seo/PerformanceChart';
import { useGscDashboard } from '../api/hooks/useGscDashboard';
import type {
  GSCBrandedSplit,
  GSCCountryRow,
  GSCDashboard,
  GSCDeviceRow,
  GSCImagePayload,
  GSCIndexationPayload,
  GSCPageCountryRow,
  GSCPageDeviceRow,
  GSCPageRow,
  GSCQueryCountryRow,
  GSCQueryDeviceRow,
  GSCQueryRow,
  GSCSearchAppearanceRow,
  GSCSitemapRow,
} from '../api/seoTypes';

const PAGE_SIZE = 25;

type TabId =
  | 'overview'
  | 'queries'
  | 'pages'
  | 'geo'
  | 'devices'
  | 'indexation'
  | 'image';

const TABS: Array<{ id: TabId; label: string; hint: string }> = [
  { id: 'overview',   label: 'Overview',     hint: 'KPIs, trend, branded vs unbranded' },
  { id: 'queries',    label: 'Queries',      hint: 'Top, underperforming, branded split' },
  { id: 'pages',      label: 'Pages',        hint: 'Top pages, geo / device per page' },
  { id: 'geo',        label: 'Geo',          hint: 'Country breakdown, NRI tail' },
  { id: 'devices',    label: 'Devices',      hint: 'Mobile vs desktop ranking gaps' },
  { id: 'indexation', label: 'Indexation',   hint: 'Coverage, rich results, sitemaps' },
  { id: 'image',      label: 'Image Search', hint: 'Image queries (Bajaj ranks here)' },
];

export default function GscPage() {
  const { data, isLoading, isError } = useGscDashboard(200);
  const [tab, setTab] = useState<TabId>('overview');

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Search Console</h1>
          <div className="seo-page-sub">
            Clicks, impressions, CTR and position from Google Search Console
            for <b>bajajlifeinsurance.com</b>. All data is read from disk —
            no live API calls.
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

      {data && data.available && (
        <>
          <div className="competitor-tab-strip">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={'tab ' + (tab === t.id ? 'active' : '')}
                onClick={() => setTab(t.id)}
                title={t.hint}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="competitor-tab-body">
            {tab === 'overview' && <OverviewTab data={data} />}
            {tab === 'queries' && <QueriesTab data={data} />}
            {tab === 'pages' && <PagesTab data={data} />}
            {tab === 'geo' && <GeoTab data={data} />}
            {tab === 'devices' && <DevicesTab data={data} />}
            {tab === 'indexation' && <IndexationTab data={data} />}
            {tab === 'image' && <ImageTab data={data.image} />}
          </div>
        </>
      )}
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────

function OverviewTab({ data }: { data: GSCDashboard }) {
  const t = data.totals!;
  const bs = data.branded_split;
  const filesCount = data.available_files
    ? Object.keys(data.available_files).length
    : 0;
  const nonEmptyFiles = data.available_files
    ? Object.values(data.available_files).filter((n) => n > 0).length
    : 0;

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
          <Kpi label="Impressions" value={compact(t.impressions)} swatch="var(--text-2)" />
          <Kpi label="Avg CTR" value={`${(t.avg_ctr * 100).toFixed(2)}%`} />
          <Kpi label="Avg Position" value={t.avg_position.toFixed(1)} />
          <Kpi label="Queries" value={compact(t.queries)} />
          <Kpi label="Pages" value={compact(t.pages)} />
        </div>
        <PerformanceChart data={data.daily_series ?? []} />
      </div>

      {bs && <BrandedRatioCard bs={bs} />}

      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Data on disk</h2>
          <span className="seo-card-sub">
            {nonEmptyFiles} of {filesCount} CSVs populated · file-backed only
          </span>
        </div>
        <table className="seo-table">
          <thead>
            <tr>
              <th>File</th>
              <th className="num">Rows</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.available_files || {})
              .sort((a, b) => b[1] - a[1])
              .slice(0, 20)
              .map(([name, n]) => (
                <tr key={name}>
                  <td className="seo-cell-query">{name}</td>
                  <td className="num">{n.toLocaleString()}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function BrandedRatioCard({ bs }: { bs: GSCBrandedSplit }) {
  const brandedPct = Math.round(bs.branded_ratio_clicks * 100);
  const unbrandedPct = 100 - brandedPct;
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Branded vs unbranded</h2>
        <span className="seo-card-sub">
          {brandedPct}% branded clicks · matched on{' '}
          {bs.tokens.slice(0, 3).join(' / ')}
          {bs.tokens.length > 3 ? '…' : ''}
        </span>
      </div>
      <div
        style={{
          display: 'flex',
          height: 28,
          borderRadius: 4,
          overflow: 'hidden',
          background: 'var(--surface-2)',
          margin: '12px 0',
        }}
        title={`${bs.branded_clicks.toLocaleString()} branded vs ${bs.unbranded_clicks.toLocaleString()} unbranded clicks`}
      >
        <div
          style={{
            width: `${brandedPct}%`,
            background: 'var(--accent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontSize: 11,
          }}
        >
          {brandedPct >= 8 ? `Branded ${brandedPct}%` : ''}
        </div>
        <div
          style={{
            width: `${unbrandedPct}%`,
            background: 'var(--text-3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontSize: 11,
          }}
        >
          {unbrandedPct >= 8 ? `Unbranded ${unbrandedPct}%` : ''}
        </div>
      </div>
      <div className="seo-perf-totals">
        <Kpi label="Branded clicks" value={compact(bs.branded_clicks)} />
        <Kpi label="Unbranded clicks" value={compact(bs.unbranded_clicks)} />
        <Kpi label="Branded queries" value={compact(bs.branded_queries)} />
        <Kpi label="Unbranded queries" value={compact(bs.unbranded_queries)} />
        <Kpi label="Branded avg pos" value={bs.branded_avg_position.toFixed(1)} />
        <Kpi label="Unbranded avg pos" value={bs.unbranded_avg_position.toFixed(1)} />
      </div>
    </div>
  );
}

// ── Queries tab ──────────────────────────────────────────────────────

function QueriesTab({ data }: { data: GSCDashboard }) {
  const [view, setView] = useState<'all' | 'branded' | 'unbranded'>('all');

  const allRows = data.top_queries ?? [];
  const bs = data.branded_split;
  const visibleRows = useMemo(() => {
    if (!bs || view === 'all') return allRows;
    const tokens = bs.tokens;
    return allRows.filter((q) => {
      const qlow = q.query.toLowerCase();
      const isBranded = tokens.some((t) => qlow.includes(t.toLowerCase()));
      return view === 'branded' ? isBranded : !isBranded;
    });
  }, [allRows, bs, view]);

  return (
    <>
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Top queries</h2>
          <span className="seo-card-sub">by clicks · filter:&nbsp;</span>
          <div style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}>
            {(['all', 'branded', 'unbranded'] as const).map((v) => (
              <button
                key={v}
                type="button"
                className={'seo-btn ' + (view === v ? '' : 'seo-btn-ghost')}
                onClick={() => setView(v)}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
        <QueryTableBody rows={visibleRows} />
      </div>

      <div className="seo-row-2-balanced">
        <QueryTable
          title="Underperforming queries"
          subtitle="position 4–15, CTR below industry curve"
          rows={data.underperforming_queries ?? []}
        />
        <QueryTable
          title="High impressions, low clicks"
          subtitle="title/meta optimisation candidates"
          rows={data.high_impression_low_click_queries ?? []}
        />
      </div>

      {bs && (
        <QueryTable
          title={`Top unbranded queries (${bs.unbranded_queries.toLocaleString()} total)`}
          subtitle="non-brand queries we earn clicks on — protect + expand"
          rows={bs.top_unbranded_queries}
        />
      )}
    </>
  );
}

// ── Pages tab ────────────────────────────────────────────────────────

function PagesTab({ data }: { data: GSCDashboard }) {
  return (
    <>
      <PageTable
        title="Top pages"
        subtitle="by clicks"
        rows={data.top_pages ?? []}
      />
      <div className="seo-row-2-balanced">
        <PageCountryTable rows={data.page_country ?? []} />
        <PageDeviceTable rows={data.page_device ?? []} />
      </div>
    </>
  );
}

// ── Geo tab ──────────────────────────────────────────────────────────

function GeoTab({ data }: { data: GSCDashboard }) {
  return (
    <>
      <CountryTable rows={data.countries ?? []} />
      <QueryCountryTable rows={data.query_country ?? []} />
    </>
  );
}

// ── Devices tab ──────────────────────────────────────────────────────

function DevicesTab({ data }: { data: GSCDashboard }) {
  const totalClicks = (data.devices ?? []).reduce(
    (acc, d) => acc + d.clicks,
    0,
  );
  return (
    <>
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Device split</h2>
          <span className="seo-card-sub">overall traffic distribution</span>
        </div>
        {totalClicks === 0 ? (
          <div className="seo-empty">No data.</div>
        ) : (
          <>
            <div
              style={{
                display: 'flex',
                height: 28,
                borderRadius: 4,
                overflow: 'hidden',
                background: 'var(--surface-2)',
                margin: '12px 0',
              }}
            >
              {(data.devices ?? []).map((d, i) => {
                const pct = (d.clicks / totalClicks) * 100;
                const colour = ['var(--accent)', 'var(--text-2)', 'var(--text-3)'][
                  i % 3
                ];
                return (
                  <div
                    key={d.device}
                    title={`${d.device}: ${d.clicks.toLocaleString()} clicks (${pct.toFixed(1)}%)`}
                    style={{
                      width: `${pct}%`,
                      background: colour,
                      color: 'white',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 11,
                    }}
                  >
                    {pct >= 8 ? `${d.device} ${pct.toFixed(0)}%` : ''}
                  </div>
                );
              })}
            </div>
            <table className="seo-table">
              <thead>
                <tr>
                  <th>Device</th>
                  <th className="num">Clicks</th>
                  <th className="num">Impr.</th>
                  <th className="num">CTR</th>
                  <th className="num">Pos</th>
                </tr>
              </thead>
              <tbody>
                {(data.devices ?? []).map((d) => (
                  <tr key={d.device}>
                    <td>{d.device}</td>
                    <td className="num">{d.clicks.toLocaleString()}</td>
                    <td className="num">{compact(d.impressions)}</td>
                    <td className="num">{(d.ctr * 100).toFixed(1)}%</td>
                    <td className="num">{d.position.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
      <QueryDeviceTable rows={data.query_device ?? []} />
    </>
  );
}

// ── Indexation tab ───────────────────────────────────────────────────

function IndexationTab({ data }: { data: GSCDashboard }) {
  return (
    <>
      <SearchAppearanceCard rows={data.search_appearances ?? []} />
      <IndexationReportCard idx={data.indexation} />
      <SitemapsCard rows={data.sitemaps ?? []} />
    </>
  );
}

function SearchAppearanceCard({ rows }: { rows: GSCSearchAppearanceRow[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Rich result types Google recognises</h2>
        <span className="seo-card-sub">
          What categories Search Console assigns our pages to (FAQ, Review
          snippet, How-To, etc.). Empty rows = Google isn't honouring the
          schema markup at scale.
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">
          No search-appearance data on disk — Google has not categorised
          our pages under any rich-result type in the pulled window.
        </div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Appearance</th>
              <th className="num">Clicks</th>
              <th className="num">Impr.</th>
              <th className="num">CTR</th>
              <th className="num">Pos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.search_appearance}>
                <td>{r.search_appearance}</td>
                <td className="num">{r.clicks.toLocaleString()}</td>
                <td className="num">{compact(r.impressions)}</td>
                <td className="num">{(r.ctr * 100).toFixed(2)}%</td>
                <td className="num">{r.position.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function IndexationReportCard({ idx }: { idx?: GSCIndexationPayload }) {
  if (!idx || !idx.available) {
    return (
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Indexation report</h2>
          <span className="seo-card-sub">
            Drop the manual GSC Coverage export under
            <code>&nbsp;backend/data/gsc/coverage/_gsc_export_*/</code>
          </span>
        </div>
        <div className="seo-empty">No manual export found.</div>
      </div>
    );
  }

  const total =
    (idx.latest_indexed ?? 0) + (idx.latest_not_indexed ?? 0);
  const indexedPct =
    total > 0 ? Math.round(((idx.latest_indexed ?? 0) / total) * 100) : 0;

  return (
    <>
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Indexation status</h2>
          <span className="seo-card-sub">
            {indexedPct}% indexed · from manual GSC UI export
          </span>
        </div>
        <div className="seo-perf-totals">
          <Kpi label="Indexed" value={(idx.latest_indexed ?? 0).toLocaleString()} />
          <Kpi
            label="Not indexed"
            value={(idx.latest_not_indexed ?? 0).toLocaleString()}
          />
          <Kpi
            label="Impressions / day"
            value={compact(idx.latest_impressions ?? 0)}
          />
        </div>
        <PerformanceChart
          data={(idx.chart ?? []).map((p) => ({
            date: p.date,
            clicks: p.indexed,        // re-purpose chart: "indexed" → "clicks" line
            impressions: p.not_indexed, // "not indexed" → "impressions" line
            ctr: 0,
            position: 0,
          }))}
        />
        <div
          style={{
            display: 'flex',
            gap: 24,
            fontSize: 12,
            color: 'var(--text-2)',
            marginTop: 8,
          }}
        >
          <span>
            <span
              className="swatch"
              style={{ background: 'var(--accent)' }}
            />{' '}
            Indexed
          </span>
          <span>
            <span
              className="swatch"
              style={{ background: 'var(--text-2)' }}
            />{' '}
            Not indexed
          </span>
        </div>
      </div>

      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Indexation issues</h2>
          <span className="seo-card-sub">
            Critical = Google can't index; Non-critical = indexed despite a
            problem. Validation = whether you've kicked off a re-check.
          </span>
        </div>
        <table className="seo-table">
          <thead>
            <tr>
              <th>Reason</th>
              <th>Source</th>
              <th>Validation</th>
              <th className="num">Pages</th>
            </tr>
          </thead>
          <tbody>
            {[...(idx.critical_issues ?? []), ...(idx.noncritical_issues ?? [])]
              .sort((a, b) => b.pages - a.pages)
              .map((r, i) => (
                <tr key={`${r.reason}-${i}`}>
                  <td className="seo-cell-query">{r.reason}</td>
                  <td>{r.source}</td>
                  <td>{r.validation}</td>
                  <td className="num">{r.pages.toLocaleString()}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SitemapsCard({ rows }: { rows: GSCSitemapRow[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Sitemaps</h2>
        <span className="seo-card-sub">
          As recorded by Search Console at last pull. ‘indexed=0’ on the
          submitted sitemap usually means GSC hasn’t reported indexed
          counts at the sitemap level — does not mean zero indexed pages.
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No sitemap data on disk.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Path</th>
              <th>Last submitted</th>
              <th>Last downloaded</th>
              <th className="num">Warnings</th>
              <th className="num">Errors</th>
              <th className="num">Submitted</th>
              <th className="num">Indexed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const sub = s.contents
                .map((c) => Number(c.submitted || 0))
                .reduce((acc, n) => acc + n, 0);
              const idx = s.contents
                .map((c) => Number(c.indexed || 0))
                .reduce((acc, n) => acc + n, 0);
              return (
                <tr key={s.path}>
                  <td className="seo-cell-query">
                    <a href={s.path} target="_blank" rel="noreferrer">
                      {s.path}
                    </a>
                  </td>
                  <td style={{ color: 'var(--text-2)', fontSize: 12 }}>
                    {(s.last_submitted || '').slice(0, 10) || '—'}
                  </td>
                  <td style={{ color: 'var(--text-2)', fontSize: 12 }}>
                    {(s.last_downloaded || '').slice(0, 10) || '—'}
                  </td>
                  <td className="num">{s.warnings}</td>
                  <td className="num">{s.errors}</td>
                  <td className="num">{sub.toLocaleString()}</td>
                  <td className="num">{idx.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Image tab ────────────────────────────────────────────────────────

function ImageTab({ data }: { data?: GSCImagePayload }) {
  if (!data) {
    return <div className="seo-empty">No image-search data on disk.</div>;
  }
  return (
    <>
      <QueryTable
        title="Top image queries"
        subtitle="Bajaj actually ranks in Google Images — alt-text targets"
        rows={data.queries}
      />
      <PageTable
        title="Top image pages"
        subtitle="pages whose images show up in image search"
        rows={data.pages}
      />
      <div className="seo-row-2-balanced">
        <CountryTable rows={data.countries} title="Image search by country" />
        <DeviceSimpleTable rows={data.devices} title="Image search by device" />
      </div>
    </>
  );
}

// ── shared sub-components ────────────────────────────────────────────

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
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>{title}</h2>
        {subtitle && <span className="seo-card-sub">{subtitle}</span>}
      </div>
      <QueryTableBody rows={rows} />
    </div>
  );
}

function QueryTableBody({ rows }: { rows: GSCQueryRow[] }) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (rows.length === 0) return <div className="seo-empty">No data.</div>;
  return (
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

function CountryTable({
  rows,
  title = 'Countries',
}: {
  rows: GSCCountryRow[];
  title?: string;
}) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>{title}</h2>
        <span className="seo-card-sub">by clicks · ISO 3166-1 alpha-3</span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Country</th>
                <th className="num">Clicks</th>
                <th className="num">Impr.</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <tr key={r.country}>
                  <td>{r.country.toUpperCase()}</td>
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

function DeviceSimpleTable({
  rows,
  title,
}: {
  rows: GSCDeviceRow[];
  title: string;
}) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>{title}</h2>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Device</th>
              <th className="num">Clicks</th>
              <th className="num">Impr.</th>
              <th className="num">CTR</th>
              <th className="num">Pos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.device}>
                <td>{r.device}</td>
                <td className="num">{r.clicks.toLocaleString()}</td>
                <td className="num">{compact(r.impressions)}</td>
                <td className="num">{(r.ctr * 100).toFixed(1)}%</td>
                <td className="num">{r.position.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function QueryCountryTable({ rows }: { rows: GSCQueryCountryRow[] }) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Query × Country</h2>
        <span className="seo-card-sub">
          Top {rows.length.toLocaleString()} (query, country) pairs by clicks
          — international + NRI tail
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Country</th>
                <th className="num">Clicks</th>
                <th className="num">Impr.</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r, i) => (
                <tr key={`${r.query}-${r.country}-${i}`}>
                  <td className="seo-cell-query" title={r.query}>
                    {r.query}
                  </td>
                  <td>{r.country.toUpperCase()}</td>
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

function QueryDeviceTable({ rows }: { rows: GSCQueryDeviceRow[] }) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Query × Device</h2>
        <span className="seo-card-sub">
          Find mobile-weak queries: same query, lower CTR on phone =
          mobile UX or AMP gap
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Device</th>
                <th className="num">Clicks</th>
                <th className="num">Impr.</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r, i) => (
                <tr key={`${r.query}-${r.device}-${i}`}>
                  <td className="seo-cell-query" title={r.query}>
                    {r.query}
                  </td>
                  <td>{r.device}</td>
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

function PageCountryTable({ rows }: { rows: GSCPageCountryRow[] }) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Page × Country</h2>
        <span className="seo-card-sub">Which pages earn international clicks</span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Page</th>
                <th>Country</th>
                <th className="num">Clicks</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r, i) => (
                <tr key={`${r.page}-${r.country}-${i}`}>
                  <td className="seo-cell-query" title={r.page}>
                    <a href={r.page} target="_blank" rel="noreferrer">
                      {shortPath(r.page)}
                    </a>
                  </td>
                  <td>{r.country.toUpperCase()}</td>
                  <td className="num">{r.clicks.toLocaleString()}</td>
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

function PageDeviceTable({ rows }: { rows: GSCPageDeviceRow[] }) {
  const [page, setPage] = useState(0);
  const slice = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Page × Device</h2>
        <span className="seo-card-sub">Mobile-weak pages</span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No data.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Page</th>
                <th>Device</th>
                <th className="num">Clicks</th>
                <th className="num">CTR</th>
                <th className="num">Pos</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r, i) => (
                <tr key={`${r.page}-${r.device}-${i}`}>
                  <td className="seo-cell-query" title={r.page}>
                    <a href={r.page} target="_blank" rel="noreferrer">
                      {shortPath(r.page)}
                    </a>
                  </td>
                  <td>{r.device}</td>
                  <td className="num">{r.clicks.toLocaleString()}</td>
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
