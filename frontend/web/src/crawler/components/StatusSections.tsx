import { Link } from 'wouter';
import Icon from './Icon';
import { fmtNum } from '../format';
import { crawlerApi, type ReportFilters, type SummaryBreakdown } from '../api';

interface Props {
  breakdown: SummaryBreakdown;
  subdomain: string; // 'all' | 'www' | 'branch' | 'investmentcorner'
}

/**
 * Reports landing — grouped section cards instead of a filter sidebar.
 *
 * Each card is a one-click drill-in: clicking sends the user to the
 * detail view for the right CSV with the right filter pre-applied via
 * URL query params (so deep links work and the back button works).
 */
export default function StatusSections({ breakdown, subdomain }: Props) {
  const subFilter: Partial<ReportFilters> = subdomain === 'all' ? {} : { subdomain };

  return (
    <div className="cc-sections">

      {/* ---- Indexing status ---- */}
      <Section
        title="Indexing status"
        hint="Indexed = confirmed by GSC impressions. Not indexed / Excluded come from a Coverage CSV or URL Inspection — never from heuristics."
      >
        <StatusCard
          icon="check_circle"
          tone="ok"
          title="Indexed by Google"
          desc="Confirmed: this URL has produced impressions or clicks in the last 16 months."
          count={breakdown.by_indexed_status.indexed}
          to={detailLink('results', { ...subFilter, indexed: 'indexed' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, indexed: 'indexed' })}
        />
        <StatusCard
          icon="cancel"
          tone="bad"
          title="Not indexed (verified)"
          desc="Coverage CSV or URL Inspection says Google saw it and chose not to index."
          count={breakdown.by_indexed_status.not_indexed}
          to={detailLink('results', { ...subFilter, indexed: 'not_indexed' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, indexed: 'not_indexed' })}
        />
        <StatusCard
          icon="block"
          tone="warn"
          title="Excluded by Google"
          desc="Cannot be indexed: 4xx, 5xx, redirected, alt-canonical, or blocked by directive."
          count={breakdown.by_indexed_status.excluded}
          to={detailLink('results', { ...subFilter, indexed: 'excluded' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, indexed: 'excluded' })}
        />
        <StatusCard
          icon="help_outline"
          tone="muted"
          title="No GSC signal yet"
          desc="Crawler found these, but no GSC impressions. Could be indexed-but-low-traffic OR not indexed. Run URL Inspection to confirm per URL."
          count={breakdown.by_indexed_status.unknown}
          to={detailLink('results', { ...subFilter, indexed: 'unknown' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, indexed: 'unknown' })}
        />
      </Section>

      {/* ---- Sitemap presence ---- */}
      <Section title="Sitemap presence" hint="Which crawled URLs were declared in sitemap.xml vs found via link-following">
        <StatusCard
          icon="map"
          tone="ok"
          title="In sitemap"
          desc="Declared in sitemap.xml and crawled"
          count={breakdown.by_sitemap_source.from_sitemap}
          to={detailLink('results', { ...subFilter, from_sitemap: '1' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, from_sitemap: '1' })}
        />
        <StatusCard
          icon="link"
          tone="muted"
          title="Discovered only"
          desc="Found via internal links — not listed in sitemap.xml"
          count={breakdown.by_sitemap_source.discovered_only}
          to={detailLink('results', { ...subFilter, from_sitemap: '0' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, from_sitemap: '0' })}
        />
        <StatusCard
          icon="report"
          tone="bad"
          title="Sitemap → broken"
          desc="In sitemap but returned non-200 (404, 5xx, etc.)"
          count={breakdown.sitemap_failed_count}
          to={detailLink('errors', { ...subFilter, from_sitemap: '1' })}
          csv={crawlerApi.downloadUrl('errors', { ...subFilter, from_sitemap: '1' })}
        />
        <StatusCard
          icon="history"
          tone="warn"
          title="Pre-existing rows (no source)"
          desc="Rows migrated from before sitemap tracking — re-crawl to populate"
          count={breakdown.by_sitemap_source.unknown_source}
          to={detailLink('results', { ...subFilter, from_sitemap: 'unknown' })}
          csv={crawlerApi.downloadUrl('results', { ...subFilter, from_sitemap: 'unknown' })}
        />
      </Section>

      {/* ---- Errors by type ---- */}
      <Section title="Errors by type" hint="One card per error-class CSV — drill in to see every failing URL.">
        <StatusCard
          icon="link_off"
          tone="bad"
          title="404 Not Found"
          count={breakdown.by_error_type.errors_404}
          to={detailLink('errors_404', subFilter)}
          csv={crawlerApi.downloadUrl('errors_404', subFilter)}
        />
        <StatusCard
          icon="http"
          tone="bad"
          title="HTTP errors (non-404)"
          desc="5xx, other 4xx"
          count={breakdown.by_error_type.errors_http}
          to={detailLink('errors_http')}
          csv={crawlerApi.downloadUrl('errors_http')}
        />
        <StatusCard
          icon="wifi_off"
          tone="warn"
          title="Connection errors"
          desc="TCP / DNS / refused connection"
          count={breakdown.by_error_type.errors_connection}
          to={detailLink('errors_connection')}
          csv={crawlerApi.downloadUrl('errors_connection')}
        />
        <StatusCard
          icon="broken_image"
          tone="warn"
          title="Chunked encoding errors"
          count={breakdown.by_error_type.errors_chunked}
          to={detailLink('errors_chunked')}
          csv={crawlerApi.downloadUrl('errors_chunked')}
        />
        <StatusCard
          icon="terminal"
          tone="muted"
          title="Console log entries"
          desc="Heuristic JS console errors found in page source"
          count={breakdown.by_error_type.console}
          to={detailLink('console', subFilter)}
          csv={crawlerApi.downloadUrl('console', subFilter)}
        />
      </Section>
    </div>
  );
}

// ── Internal components ────────────────────────────────────────────────

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="cc-section">
      <header className="cc-section__head">
        <h2 className="cc-section__title">{title}</h2>
        {hint && <span className="cc-section__hint">{hint}</span>}
      </header>
      <div className="cc-section__grid">{children}</div>
    </section>
  );
}

function StatusCard({
  icon,
  tone,
  title,
  desc,
  count,
  to,
  csv,
}: {
  icon: string;
  tone: 'ok' | 'bad' | 'warn' | 'muted';
  title: string;
  desc?: string;
  count: number;
  to: string;
  csv?: string;
}) {
  const dim = count === 0;
  return (
    <div className={`cc-card cc-card--${tone}${dim ? ' cc-card--dim' : ''}`}>
      <div className="cc-card__icon"><Icon name={icon} /></div>
      <div className="cc-card__body">
        <div className="cc-card__title">{title}</div>
        {desc && <div className="cc-card__desc">{desc}</div>}
      </div>
      <div className="cc-card__count">{fmtNum(count)}</div>
      <div className="cc-card__actions">
        <Link href={to} className="btn btn-ghost">
          <Icon name="visibility" /> View
        </Link>
        {csv && (
          <a href={csv} className="btn btn-primary">
            <Icon name="download" /> CSV
          </a>
        )}
      </div>
    </div>
  );
}

function detailLink(tableKey: string, filters?: Partial<ReportFilters>): string {
  const qs = new URLSearchParams();
  if (filters?.subdomain) qs.set('subdomain', filters.subdomain);
  if (filters?.category) qs.set('category', filters.category);
  if (filters?.indexed) qs.set('indexed', filters.indexed);
  if (filters?.from_sitemap !== undefined && filters.from_sitemap !== '')
    qs.set('from_sitemap', filters.from_sitemap);
  if (filters?.hide_branch_404_noise) qs.set('noise', 'hide');
  const s = qs.toString();
  return `/crawler/reports/${tableKey}${s ? `?${s}` : ''}`;
}
