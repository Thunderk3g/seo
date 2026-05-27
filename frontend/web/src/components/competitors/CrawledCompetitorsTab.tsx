// "Crawled Competitors" tab — surfaces the Phase G Scrapy walk output.
//
// Reads /api/v1/seo/competitor/crawls/ which returns every domain we've
// ever crawled (latest complete snapshot per domain) with page counts +
// change-event totals. Each row is clickable and routes to
// /competitors/<domain>/ which reads the per-competitor detail from
// CrawlerPageResult (see backend competitor_detail_view, BUG-031 fix).
//
// This is the "did my overnight crawl produce data?" panel — separate
// from the gap-detection pipeline, which only shows domains that the
// pipeline itself discovered + crawled.

import { Link } from 'wouter';
import { useCompetitorCrawls } from '../../api/hooks/useCompetitorCrawls';
import type { CompetitorCrawlRow } from '../../api/hooks/useCompetitorCrawls';

function formatRelative(iso: string | null): string {
  if (!iso) return '—';
  try {
    const ts = new Date(iso).getTime();
    const ageSec = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (ageSec < 60) return `${ageSec}s ago`;
    if (ageSec < 3600) return `${Math.round(ageSec / 60)}m ago`;
    if (ageSec < 86400) return `${Math.round(ageSec / 3600)}h ago`;
    return `${Math.round(ageSec / 86400)}d ago`;
  } catch {
    return iso;
  }
}

function Row({ c }: { c: CompetitorCrawlRow }) {
  const okRatio =
    c.pages_attempted > 0
      ? Math.round((c.pages_ok / c.pages_attempted) * 100)
      : 0;
  return (
    <tr>
      <td className="seo-cell-query">
        <Link
          href={`/competitors/${encodeURIComponent(c.domain)}`}
          style={{
            color: 'var(--accent)',
            textDecoration: 'none',
            fontWeight: 500,
          }}
        >
          {c.domain}
        </Link>
      </td>
      <td className="num">{c.pages_in_db.toLocaleString()}</td>
      <td className="num">
        {c.pages_ok}/{c.pages_attempted}
        {c.pages_attempted > 0 && (
          <span style={{ color: 'var(--text-3)', marginLeft: 6 }}>
            ({okRatio}%)
          </span>
        )}
      </td>
      <td className="num">{c.change_events.toLocaleString()}</td>
      <td style={{ color: 'var(--text-2)', fontSize: 12 }}>
        {formatRelative(c.started_at)}
      </td>
    </tr>
  );
}

export default function CrawledCompetitorsTab() {
  const { data, isLoading, isError, error } = useCompetitorCrawls();

  if (isLoading) {
    return (
      <div className="seo-empty">Loading crawled-competitors list…</div>
    );
  }
  if (isError) {
    return (
      <div className="seo-error">
        Failed to load crawled competitors:{' '}
        {error instanceof Error ? error.message : 'unknown error'}
      </div>
    );
  }
  const rows = data?.competitors || [];
  if (rows.length === 0) {
    return (
      <div className="seo-empty">
        No competitor crawls yet. The daily Scrapy walk runs at 03:00 IST
        — or trigger one manually with{' '}
        <code>python manage.py crawl_competitor &lt;domain&gt;</code>.
      </div>
    );
  }

  // Sort: most-recent first. Ties on freshness, fall back to pages_in_db
  // so a freshly-crawled-but-empty domain sinks below older productive ones.
  const ordered = [...rows].sort((a, b) => {
    const aTs = a.started_at ? Date.parse(a.started_at) : 0;
    const bTs = b.started_at ? Date.parse(b.started_at) : 0;
    if (aTs !== bTs) return bTs - aTs;
    return b.pages_in_db - a.pages_in_db;
  });

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Crawled competitors ({data?.count ?? 0})</h2>
        <span className="seo-card-sub">
          Every competitor domain the Phase G Scrapy walk has visited.
          Polls every 30 s so an overnight run lights up rows here as
          they finish. Click a row to open the per-competitor profile.
        </span>
      </div>
      <table className="seo-table">
        <thead>
          <tr>
            <th>Domain</th>
            <th className="num">Pages in DB</th>
            <th className="num">OK / attempted</th>
            <th className="num">Change events</th>
            <th>Last crawl</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((c) => (
            <Row key={c.snapshot_id} c={c} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
