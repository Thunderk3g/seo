import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useParams } from 'wouter';
import DataTable from '../components/DataTable';
import EmptyState from '../components/EmptyState';
import Icon from '../components/Icon';
import ReportFiltersPanel from '../components/ReportFilters';
import {
  crawlerApi,
  type ReportFilters,
  type SummaryBreakdown,
  type TableData,
} from '../api';

export default function CrawlerReportDetail() {
  const params = useParams<{ key: string }>();
  const key = params.key;
  const [data, setData] = useState<TableData | null>(null);
  const [breakdown, setBreakdown] = useState<SummaryBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [location, setLocation] = useLocation();

  const filters = useMemo(() => readFilters(location), [location]);

  function updateFilters(next: ReportFilters) {
    setLocation(`/crawler/reports/${key}${writeFilters(next)}`);
  }

  // Re-load on key or filter change.
  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    crawlerApi
      .table(key, filters)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [key, location]); // eslint-disable-line react-hooks/exhaustive-deps

  // Breakdown loaded once — needed for the "hide branch 404 noise" badge count.
  useEffect(() => {
    let alive = true;
    crawlerApi.breakdown().then((b) => alive && setBreakdown(b)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const activeFilterChips = chipsFromFilters(filters);

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Link href="/crawler/reports" className="btn btn-ghost" style={{ padding: '4px 10px' }}>
              <Icon name="arrow_back" size="16px" /> Back to reports
            </Link>
            {activeFilterChips.length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {activeFilterChips.map((chip) => (
                  <span key={chip.key} className="cc-tab__chip cc-tab__chip--ok">
                    <strong>{chip.label}</strong>: {chip.value}
                  </span>
                ))}
              </div>
            )}
          </div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              description
            </span>
            {data?.label || key}
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              info
            </span>
            {data?.description}
            {data ? <span style={{ marginLeft: 10, color: 'var(--text-muted)' }}>· {data.count.toLocaleString()} rows</span> : null}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <a className="btn btn-ghost" href={crawlerApi.downloadUrl(key, filters)}>
            <Icon name="download" /> Filtered CSV
          </a>
          <a className="btn btn-accent" href={crawlerApi.xlsxUrl()}>
            <Icon name="insert_chart" /> Full XLSX
          </a>
        </div>
      </div>

      <div className="cc-reports-grid">
        <ReportFiltersPanel
          value={filters}
          onChange={updateFilters}
          noiseCount={breakdown?.noise_404_branch_not_indexed}
        />
        <div>
          {error && <EmptyState icon="error" title="Could not load table" hint={error} />}
          {!error && data && data.count === 0 && (
            <EmptyState
              icon="inbox"
              title="No rows match these filters"
              hint="Loosen the filters above or run a fresh crawl."
            />
          )}
          {!error && data && data.count > 0 && (
            <DataTable headers={data.headers} rows={data.rows} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Filter <-> URL helpers (mirrors CrawlerReports.tsx) ─────────────────
function readFilters(loc: string): ReportFilters {
  const qIdx = loc.indexOf('?');
  if (qIdx < 0) return {};
  const sp = new URLSearchParams(loc.slice(qIdx + 1));
  const out: ReportFilters = {};
  const sub = sp.get('subdomain') ?? sp.get('sub');
  const cat = sp.get('category') ?? sp.get('cat');
  if (sub) out.subdomain = sub;
  if (cat) out.category = cat;
  if (sp.get('indexed')) out.indexed = sp.get('indexed') ?? undefined;
  if (sp.get('from_sitemap')) out.from_sitemap = sp.get('from_sitemap') ?? undefined;
  if (sp.get('page_type')) out.page_type = sp.get('page_type') ?? undefined;
  if (sp.get('noise') === 'hide' || sp.get('hide_branch_404_noise') === '1') {
    out.hide_branch_404_noise = true;
  }
  return out;
}

function writeFilters(f: ReportFilters): string {
  const qs = new URLSearchParams();
  if (f.subdomain) qs.set('subdomain', f.subdomain);
  if (f.category) qs.set('category', f.category);
  if (f.indexed) qs.set('indexed', f.indexed);
  if (f.from_sitemap) qs.set('from_sitemap', f.from_sitemap);
  if (f.page_type) qs.set('page_type', f.page_type);
  if (f.hide_branch_404_noise) qs.set('noise', 'hide');
  const s = qs.toString();
  return s ? `?${s}` : '';
}

function chipsFromFilters(f: ReportFilters): { key: string; label: string; value: string }[] {
  const chips: { key: string; label: string; value: string }[] = [];
  if (f.subdomain) chips.push({ key: 'subdomain', label: 'Subdomain', value: f.subdomain });
  if (f.category) chips.push({ key: 'category', label: 'Category', value: f.category });
  if (f.indexed) chips.push({ key: 'indexed', label: 'Indexed', value: f.indexed });
  if (f.from_sitemap)
    chips.push({
      key: 'from_sitemap',
      label: 'Source',
      value: f.from_sitemap === '1' ? 'sitemap' : 'links',
    });
  if (f.hide_branch_404_noise)
    chips.push({ key: 'noise', label: 'Noise', value: 'hidden' });
  return chips;
}
