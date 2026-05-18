import { useEffect, useMemo, useState } from 'react';
import { useSearch } from 'wouter';
import GscCoverageUploader from '../components/GscCoverageUploader';
import Icon from '../components/Icon';
import StatusSections from '../components/StatusSections';
// SubdomainTabs removed per request (Main site / Branch / InvCorner counts row).
// Subdomain filter still works via ?subdomain=www style URLs for deep linking.
import { crawlerApi, type SummaryBreakdown, type TablesResponse } from '../api';

type SubKey = 'all' | 'www' | 'branch' | 'investmentcorner';

/**
 * Reports landing page — sectioned by what actually matters operationally:
 *
 *   1. Indexing status (from GSC Coverage CSV)
 *      indexed / not_indexed / excluded / unknown
 *   2. Sitemap presence
 *      in sitemap / discovered only / sitemap-broken
 *   3. Errors by type
 *      404 / HTTP / connection / chunked / console
 *
 * No filter sidebar — drilling in is a click on a card, which
 * navigates to the detail view with the right filter pre-applied.
 */
export default function CrawlerReports() {
  const [tables, setTables] = useState<TablesResponse | null>(null);
  const [breakdown, setBreakdown] = useState<SummaryBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  // wouter v3: useLocation returns pathname only; query string lives in useSearch.
  const search = useSearch();

  // Subdomain scope is still respected via deep-link URLs (?subdomain=www),
  // it just no longer has visible tab UI.
  const subdomain = useMemo<SubKey>(() => parseSubdomain(search), [search]);

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
            Indexing status, sitemap coverage, and error breakdown — pulled from your latest crawl
            and the most recent Google Search Console Coverage export.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
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

      {breakdown ? (
        <StatusSections breakdown={breakdown} subdomain={subdomain} />
      ) : (
        !error && <div className="cc-empty"><Icon name="hourglass_empty" /> Loading breakdown…</div>
      )}

      {tables && tables.tables.length > 0 && (
        <details className="cc-raw-tables">
          <summary>
            <Icon name="dataset" /> Raw data tables ({tables.tables.length} files in backend/data/)
          </summary>
          <ul className="cc-raw-tables__list">
            {tables.tables.map((t) => (
              <li key={t.key}>
                <a href={`/crawler/reports/${t.key}`}>
                  <Icon name={t.icon} />
                  <span className="cc-raw-tables__label">{t.label}</span>
                  <span className="cc-raw-tables__count">{t.count.toLocaleString()}</span>
                </a>
                <a className="cc-raw-tables__csv" href={crawlerApi.downloadUrl(t.key)}>
                  <Icon name="download" /> CSV
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function parseSubdomain(search: string): SubKey {
  if (!search) return 'all';
  const q = search.startsWith('?') ? search.slice(1) : search;
  if (!q) return 'all';
  const sp = new URLSearchParams(q);
  const v = (sp.get('subdomain') ?? sp.get('sub') ?? 'all') as SubKey;
  return (['all', 'www', 'branch', 'investmentcorner'] as const).includes(v as any) ? v : 'all';
}
