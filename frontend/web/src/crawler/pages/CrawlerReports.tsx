import { useEffect, useState } from 'react';
import Icon from '../components/Icon';
import CrawlHistoryPanel from '../components/CrawlHistoryPanel';
import PsiStatusBanner from '../components/PsiStatusBanner';
import ReportSectionsPanel from '../components/ReportSectionsPanel';
// Index/not-indexed (StatusSections + GscCoverageUploader) deferred — the
// live section-wise report below (ReportSectionsPanel) is the new main view.
import { crawlerApi, type TablesResponse } from '../api';

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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    crawlerApi.tables()
      .then((t) => alive && setTables(t))
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
            Redirects, soft-404s, sitemap coverage, robots.txt, internal/external linking,
            PDF health, and broken links (with proof of the source page) — from your latest crawl.
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

      <PsiStatusBanner />

      <ReportSectionsPanel />

      <CrawlHistoryPanel />

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
