// AdobePage — Adobe Analytics 2.0 dashboard (Bajaj Life Insurance).
//
// Backend `/api/v1/seo/adobe/` returns:
//   report_suite, totals, top_pages, daily_trend, channels,
//   entry_pages, countries, devices, dimension_count, metric_count
//
// Sections (top → bottom):
//   1. Header + lookback / top-N selectors
//   2. KPI strip
//   3. Time-series (page-views + visits, 30-day trend)
//   4. Marketing channels (donut + table)
//   5. Top pages (sortable table)
//   6. Entry pages (with bounce-rate + time-on-page)
//   7. Geography / Device tabs (each = bars + table)
//
// All charts are pure SVG via components/charts/* — no new chart lib.

import { useMemo, useState } from 'react';
import {
  useAdobeDashboard,
  type AdobeDashboardResponse,
  type AdobeTopPageRow,
  type AdobeEntryPageRow,
  type AdobeChannelRow,
  type AdobeGeoRow,
  type AdobeDeviceRow,
} from '../api/hooks/useAdobeDashboard';
import TimeSeriesChart from '../components/charts/TimeSeriesChart';
import MiniDonut from '../components/charts/MiniDonut';

const LOOKBACK_OPTIONS = [7, 14, 30];
const LIMIT_OPTIONS = [25, 50, 100];

// Recurring palette for channel donut + geo bars.
const PALETTE = [
  '#0072ce', // Bajaj blue
  '#21a884',
  '#f4a300',
  '#d24a3e',
  '#7b6cc4',
  '#15788c',
  '#c46b14',
  '#3c6d28',
  '#888aa0',
  '#9f4d99',
];

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
  const topPages = data.top_pages ?? [];
  const trend = data.daily_trend ?? [];
  const channels = data.channels ?? [];
  const entryPages = data.entry_pages ?? [];
  const countries = data.countries ?? [];
  const devices = data.devices ?? [];

  return (
    <>
      {/* ── KPI strip ───────────────────────────────────────────── */}
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

      {/* ── Time-series ─────────────────────────────────────────── */}
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Daily trend</h2>
          <span className="seo-card-sub">
            Last {trend.length || 30} days · page-views and visits
          </span>
        </div>
        <TimeSeriesChart
          data={trend.map((p) => ({
            date: p.date,
            'Page views': p.page_views,
            Visits: p.visits,
          }))}
          series={[
            {
              key: 'Page views',
              label: 'Page views',
              color: 'var(--accent)',
              fill: true,
            },
            { key: 'Visits', label: 'Visits', color: '#21a884' },
          ]}
          height={240}
        />
      </div>

      {/* ── Marketing channels ──────────────────────────────────── */}
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Marketing channels</h2>
          <span className="seo-card-sub">
            Visits by channel · Last {data.lookback_days ?? '?'} days
          </span>
        </div>
        <ChannelsSection rows={channels} />
      </div>

      {/* ── Top pages ────────────────────────────────────────────── */}
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Top pages by page-views</h2>
          <span className="seo-card-sub">
            Sorted by page-view count · {topPages.length} rows
          </span>
        </div>
        {topPages.length === 0 ? (
          <div className="seo-empty">
            No rows returned for this window. Widen the lookback or check
            that the report suite has traffic.
          </div>
        ) : (
          <TopPagesTable rows={topPages} />
        )}
      </div>

      {/* ── Entry pages ─────────────────────────────────────────── */}
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Entry pages</h2>
          <span className="seo-card-sub">
            With bounce rate + avg time on page
          </span>
        </div>
        {entryPages.length === 0 ? (
          <div className="seo-empty">
            No entry-page data for this window.
          </div>
        ) : (
          <EntryPagesTable rows={entryPages} />
        )}
      </div>

      {/* ── Geo / Device tabs ───────────────────────────────────── */}
      <div className="seo-card">
        <GeoDeviceTabs countries={countries} devices={devices} />
      </div>

      {/* Capability footer */}
      <div className="seo-card-foot">
        <span>
          {data.dimension_count ?? 0} dimensions · {data.metric_count ?? 0}{' '}
          metrics · report suite "{data.report_suite?.name ?? '?'}".
        </span>
      </div>
    </>
  );
}

// ── Section: Marketing channels (donut + table) ──────────────────────
function ChannelsSection({ rows }: { rows: AdobeChannelRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="seo-empty">
        No marketing-channel data for this window. The dimension
        <code>variables/marketingchannel</code> may not be enabled on the
        report suite.
      </div>
    );
  }
  const donutEntries = rows.slice(0, 8).map((r, i) => ({
    label: r.channel,
    count: r.visits,
    color: PALETTE[i % PALETTE.length],
  }));
  return (
    <div className="seo-channels-row">
      <MiniDonut
        entries={donutEntries}
        size={180}
        thickness={22}
        centerLabel="Channels"
      />
      <table className="seo-table seo-table-compact">
        <thead>
          <tr>
            <th>Channel</th>
            <th style={{ textAlign: 'right' }}>Visits</th>
            <th style={{ textAlign: 'right' }}>Share</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.channel}-${i}`}>
              <td>
                <span
                  className="seo-swatch"
                  style={{ background: PALETTE[i % PALETTE.length] }}
                />
                {r.channel || <i>(unset)</i>}
              </td>
              <td className="seo-num">{r.visits.toLocaleString()}</td>
              <td className="seo-num">{r.share_pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Section: Top pages (sortable) ────────────────────────────────────
type SortKey = 'page' | 'page_views';

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
    if (sortKey === k) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k);
      setSortDir(k === 'page' ? 'asc' : 'desc');
    }
  };

  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th onClick={() => setSort('page')} style={{ cursor: 'pointer' }}>
            Page{sortKey === 'page' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </th>
          <th
            onClick={() => setSort('page_views')}
            style={{ cursor: 'pointer', textAlign: 'right' }}
          >
            Page views
            {sortKey === 'page_views' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
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

// ── Section: Entry pages ─────────────────────────────────────────────
function EntryPagesTable({ rows }: { rows: AdobeEntryPageRow[] }) {
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Page</th>
          <th style={{ textAlign: 'right' }}>Entries</th>
          <th style={{ textAlign: 'right' }}>Bounce rate</th>
          <th style={{ textAlign: 'right' }}>Avg time</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, idx) => {
          // bounce_rate is a fraction 0–1; some Adobe configs return 0–100.
          const br = r.bounce_rate > 1 ? r.bounce_rate : r.bounce_rate * 100;
          return (
            <tr key={r.item_id || `${r.page}-${idx}`}>
              <td className="seo-num">{idx + 1}</td>
              <td>{r.page || <i>(unset)</i>}</td>
              <td className="seo-num">{r.entries.toLocaleString()}</td>
              <td className="seo-num">{br.toFixed(1)}%</td>
              <td className="seo-num">{formatDuration(r.time_on_page_sec)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Section: Geo / Device tabs ───────────────────────────────────────
function GeoDeviceTabs({
  countries,
  devices,
}: {
  countries: AdobeGeoRow[];
  devices: AdobeDeviceRow[];
}) {
  const [tab, setTab] = useState<'geo' | 'device'>('geo');
  return (
    <>
      <div className="seo-card-head">
        <div className="seo-tabs">
          <button
            type="button"
            className={`seo-tab ${tab === 'geo' ? 'active' : ''}`}
            onClick={() => setTab('geo')}
          >
            Geography
          </button>
          <button
            type="button"
            className={`seo-tab ${tab === 'device' ? 'active' : ''}`}
            onClick={() => setTab('device')}
          >
            Device
          </button>
        </div>
        <span className="seo-card-sub">
          {tab === 'geo'
            ? 'Top countries by visits'
            : 'Mobile / Tablet / Desktop split'}
        </span>
      </div>
      {tab === 'geo' ? (
        <ShareTable
          rows={countries.map((c) => ({
            label: c.label,
            count: c.visits,
            share: c.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No country data for this window."
        />
      ) : (
        <ShareTable
          rows={devices.map((d) => ({
            label: d.device_type,
            count: d.visits,
            share: d.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No device data for this window."
        />
      )}
    </>
  );
}

function ShareTable({
  rows,
  unit,
  emptyMsg,
}: {
  rows: { label: string; count: number; share: number }[];
  unit: string;
  emptyMsg: string;
}) {
  if (rows.length === 0) {
    return <div className="seo-empty">{emptyMsg}</div>;
  }
  const max = rows.reduce((m, r) => (r.count > m ? r.count : m), 0) || 1;
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Label</th>
          <th style={{ textAlign: 'right' }}>{unit}</th>
          <th style={{ textAlign: 'right' }}>Share</th>
          <th style={{ width: 220 }}>&nbsp;</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.label}-${i}`}>
            <td className="seo-num">{i + 1}</td>
            <td>{r.label || <i>(unset)</i>}</td>
            <td className="seo-num">{r.count.toLocaleString()}</td>
            <td className="seo-num">{r.share.toFixed(1)}%</td>
            <td>
              <div className="seo-bar">
                <div
                  className="seo-bar-fill"
                  style={{
                    width: `${(r.count / max) * 100}%`,
                    background: PALETTE[i % PALETTE.length],
                  }}
                />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── shared bits ──────────────────────────────────────────────────────
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

function formatDuration(sec: number): string {
  if (!sec || Number.isNaN(sec)) return '—';
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec - m * 60);
  return `${m}m ${s}s`;
}
