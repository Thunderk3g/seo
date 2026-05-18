import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'wouter';
import BreakdownGrid from '../components/BreakdownGrid';
import CategoryTabs from '../components/CategoryTabs';
import GscCoverageUploader from '../components/GscCoverageUploader';
import Icon from '../components/Icon';
import ReportCard from '../components/ReportCard';
import ReportFiltersPanel from '../components/ReportFilters';
import SubdomainTabs from '../components/SubdomainTabs';
import {
  crawlerApi,
  type ReportFilters,
  type SummaryBreakdown,
  type TableMeta,
  type TablesResponse,
} from '../api';

type SubKey = 'all' | 'www' | 'branch' | 'investmentcorner';

const CATEGORISED_KEYS = new Set([
  'results',
  'errors',
  'errors_404',
  'discovered',
  'console',
]);

/**
 * The Reports page is the heart of the Crawler Engine UI. It used to be a
 * flat grid of `ReportCard`s; the rewrite below organises everything by
 * subdomain → category, with a sidebar of orthogonal filters (indexed
 * status, sitemap origin, branch-noise toggle) and a banner for plugging
 * in GSC Coverage data.
 *
 * Filter state lives in the URL (?sub=, ?cat=, ?indexed=, ?noise=) so deep
 * links from the rest of the app continue to work.
 */
export default function CrawlerReports() {
  const [tables, setTables] = useState<TablesResponse | null>(null);
  const [breakdown, setBreakdown] = useState<SummaryBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [location, setLocation] = useLocation();

  // ── URL-synced filter state ──────────────────────────────────────────
  const filters = useMemo(() => readFilters(location), [location]);
  const subdomain: SubKey = (filters.subdomain as SubKey) || 'all';
  const category = filters.category ?? null;

  function updateFilters(next: ReportFilters) {
    setLocation('/crawler/reports' + writeFilters(next));
  }
  function setSubdomain(s: SubKey) {
    const { category: _c, ...rest } = filters;
    updateFilters({ ...rest, subdomain: s === 'all' ? undefined : s });
  }
  function setCategory(c: string | null) {
    updateFilters({ ...filters, category: c ?? undefined });
  }

  // ── Data load ────────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    Promise.all([crawlerApi.tables(), crawlerApi.breakdown()])
      .then(([t, b]) => {
        if (!alive) return;
        setTables(t);
        setBreakdown(b);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, []);

  // ── Derived data for the active scope ────────────────────────────────
  const activeTable = useMemo(() => {
    if (!tables) return null;
    // We surface the categorised "results" table as the primary grid;
    // user can switch focus by clicking individual ReportCards below.
    return tables.tables.find((t) => t.key === 'results') ?? null;
  }, [tables]);

  const filteredCategories = useMemo(() => {
    if (!breakdown) return [];
    return breakdown.categories.filter((c) =>
      subdomain === 'all' ? true : c.subdomain === subdomain,
    );
  }, [breakdown, subdomain]);

  const nonCategorisedTables = useMemo<TableMeta[]>(() => {
    if (!tables) return [];
    return tables.tables.filter((t) => !CATEGORISED_KEYS.has(t.key));
  }, [tables]);

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              assessment
            </span>
            Reports
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              segment
            </span>
            Crawl artefacts segregated by subdomain, page category, and Google index status.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <a className="btn btn-ghost" href={crawlerApi.downloadUrl('results', filters)}>
            <Icon name="download" /> Filtered CSV
          </a>
          <a className="btn btn-accent" href={crawlerApi.xlsxUrl()}>
            <Icon name="insert_chart" /> Download Excel Bundle
          </a>
        </div>
      </div>

      {error && (
        <div className="card" style={{ padding: 16, borderColor: 'var(--red)', color: 'var(--red)' }}>
          <Icon name="error" /> {error}
        </div>
      )}

      <GscCoverageUploader />

      <SubdomainTabs
        value={subdomain}
        onChange={setSubdomain}
        bySubdomain={breakdown?.by_subdomain}
      />
      {breakdown && (
        <CategoryTabs
          categories={breakdown.categories}
          subdomain={subdomain}
          value={category}
          onChange={setCategory}
        />
      )}

      <div className="cc-reports-grid">
        <ReportFiltersPanel
          value={filters}
          onChange={updateFilters}
          noiseCount={breakdown?.noise_404_branch_not_indexed}
        />
        <div>
          <h3 style={{ margin: '4px 0 8px', fontSize: 14, color: 'var(--text-secondary)' }}>
            {activeTable?.label ?? 'Crawl results'} — by category
          </h3>
          {breakdown && (
            <BreakdownGrid
              categories={filteredCategories}
              filters={filters}
              tableKey="results"
            />
          )}

          {nonCategorisedTables.length > 0 && (
            <>
              <h3 style={{ margin: '24px 0 8px', fontSize: 14, color: 'var(--text-secondary)' }}>
                Other tables
              </h3>
              <div className="report-grid">
                {nonCategorisedTables.map((t) => (
                  <ReportCard key={t.key} table={t} />
                ))}
              </div>
            </>
          )}

          <div style={{ marginTop: 18, fontSize: 12, color: 'var(--text-muted)' }}>
            <Icon name="info" size="14px" /> Tip — click any category card to drill into the filtered
            row list. The CSV download honours every filter you have set above.{' '}
            <Link href="/crawler/reports?indexed=not_indexed&subdomain=www">
              Show only www pages Google did not index →
            </Link>
          </div>
        </div>
      </div>
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
