import { Link } from 'wouter';
import Icon from './Icon';
import { fmtNum } from '../format';
import { crawlerApi, type CategoryMeta, type ReportFilters } from '../api';

interface Props {
  categories: CategoryMeta[];
  filters: ReportFilters;
  tableKey: string; // which CSV the cards link to (e.g. "results" or "errors_404")
}

/**
 * Category-aware grid that replaces the flat ReportCard list when the user
 * is in a categorised table (results / errors / errors_404 / discovered /
 * console). One card per category with a non-zero crawled count.
 */
export default function BreakdownGrid({ categories, filters, tableKey }: Props) {
  const visible = categories.filter((c) => (c.counts?.crawled ?? 0) > 0);
  if (visible.length === 0) {
    return (
      <div className="cc-empty">
        <Icon name="dataset" />
        <div>No data in this surface yet — run a crawl first.</div>
      </div>
    );
  }

  return (
    <div className="report-grid">
      {visible.map((c) => {
        const ni = c.counts?.not_indexed ?? 0;
        const ok = c.counts?.indexed ?? 0;
        const total = c.counts?.crawled ?? 0;
        const errs = c.counts?.errors ?? 0;
        const scopedFilters: ReportFilters = { ...filters, category: c.key };
        return (
          <div key={c.key} className="report-card">
            <div className="rc-head">
              <div className="rc-icon">
                <Icon name={c.icon} />
              </div>
              <div>
                <div className="rc-title">{c.label}</div>
                <div className="rc-count">{fmtNum(total)}</div>
              </div>
            </div>
            <div className="rc-meta">
              <span className="rc-chip rc-chip--ok" title="Indexed by Google">
                <Icon name="check_circle" /> {fmtNum(ok)}
              </span>
              <span
                className={`rc-chip ${ni > 0 ? 'rc-chip--bad' : ''}`}
                title="Not indexed by Google"
              >
                <Icon name="cancel" /> {fmtNum(ni)}
              </span>
              <span
                className={`rc-chip ${errs > 0 ? 'rc-chip--warn' : ''}`}
                title="Crawl errors"
              >
                <Icon name="error" /> {fmtNum(errs)}
              </span>
            </div>
            <div className="rc-actions">
              <Link
                href={`/crawler/reports/${tableKey}?${categoryQS(scopedFilters)}`}
                className="btn btn-ghost"
                style={{ flex: 1, justifyContent: 'center' }}
              >
                <Icon name="visibility" /> View
              </Link>
              <a
                href={crawlerApi.downloadUrl(tableKey, scopedFilters)}
                className="btn btn-primary"
                style={{ flex: 1, justifyContent: 'center' }}
              >
                <Icon name="download" /> CSV
              </a>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function categoryQS(f: ReportFilters): string {
  const qs = new URLSearchParams();
  if (f.subdomain) qs.set('subdomain', f.subdomain);
  if (f.category) qs.set('category', f.category);
  if (f.indexed) qs.set('indexed', f.indexed);
  if (f.from_sitemap) qs.set('from_sitemap', f.from_sitemap);
  if (f.hide_branch_404_noise) qs.set('hide_branch_404_noise', '1');
  return qs.toString();
}
