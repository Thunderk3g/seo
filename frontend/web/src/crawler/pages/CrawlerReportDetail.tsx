import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useParams } from 'wouter';
import DataTable from '../components/DataTable';
import EmptyState from '../components/EmptyState';
import Icon from '../components/Icon';
import { crawlerApi, type ReportFilters, type TableData } from '../api';

/**
 * Report detail — shows one CSV with any filters from the URL applied.
 * No sidebar UI. Filters are passed in by the card that linked here and
 * surfaced as chips at the top of the page so the user can see what's
 * active and clear individual filters.
 */
export default function CrawlerReportDetail() {
  const params = useParams<{ key: string }>();
  const key = params.key;
  const [data, setData] = useState<TableData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [location, setLocation] = useLocation();

  const filters = useMemo(() => readFilters(location), [location]);

  function clearFilter(name: keyof ReportFilters) {
    const next: ReportFilters = { ...filters };
    delete next[name];
    setLocation(`/crawler/reports/${key}${writeFilters(next)}`);
  }

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

  const chips = chipsFromFilters(filters);

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
            <Link href="/crawler/reports" className="btn btn-ghost" style={{ padding: '4px 10px' }}>
              <Icon name="arrow_back" size="16px" /> Back to reports
            </Link>
            {chips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                className="cc-active-chip"
                title="Click to remove this filter"
                onClick={() => clearFilter(chip.key as keyof ReportFilters)}
              >
                <strong>{chip.label}</strong>: {chip.value}
                <Icon name="close" />
              </button>
            ))}
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
            <Icon name="download" /> {chips.length ? 'Filtered CSV' : 'CSV'}
          </a>
          <a className="btn btn-accent" href={crawlerApi.xlsxUrl()}>
            <Icon name="insert_chart" /> Full XLSX
          </a>
        </div>
      </div>

      {error && <EmptyState icon="error" title="Could not load table" hint={error} />}
      {!error && data && data.count === 0 && (
        <EmptyState
          icon="inbox"
          title="No rows match these filters"
          hint={chips.length ? "Clear a chip above to widen the search." : "Run a crawl to populate this table."}
        />
      )}
      {!error && data && data.count > 0 && (
        <DataTable headers={data.headers} rows={data.rows} />
      )}
    </div>
  );
}

// ── Filter <-> URL helpers ──────────────────────────────────────────────
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
      value: f.from_sitemap === '1' ? 'sitemap' : f.from_sitemap === '0' ? 'links only' : f.from_sitemap,
    });
  if (f.hide_branch_404_noise)
    chips.push({ key: 'hide_branch_404_noise', label: 'Noise', value: 'hidden' });
  return chips;
}
