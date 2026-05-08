// CrawlOverviewCard — text-row summary of the active crawl session.
//
// Mirrors `.design-ref/project/dashboard.jsx` CrawlOverviewCard (lines
// 91-118). Renders a vertical stack of label : value rows.
//
// NOTE on prop type: spec text named `CrawlSessionDetail | null`, but the
// fields we render (started_at, duration, response time, depth, totals) all
// live on `CrawlSessionListItem` which is what `useSessions` already
// returns. `CrawlSessionDetail` extends list, so list is a strict subset
// — taking the lighter type lets the dashboard render without firing a
// second per-session request.
//
// The design also showed UA / JS render / robots.txt rows, but those live
// on `CrawlConfig` (per-website settings) rather than the session itself.
// They're left out of v1 to avoid pulling settings into the dashboard
// fetch graph; revisit when an "open session" drawer lands.

import type { CrawlSessionListItem } from '../../api/types';

interface Props {
  session: CrawlSessionListItem | null;
}

function formatStarted(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—';
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${h}h ${mm}m`;
}

export default function CrawlOverviewCard({ session }: Props) {
  if (!session) {
    return (
      <div className="card">
        <div className="card-head">
          <h3>Crawl overview</h3>
        </div>
        <p className="text-muted" style={{ fontSize: 12 }}>
          No crawl session yet.
        </p>
      </div>
    );
  }

  const rows: [string, string | number][] = [
    ['Started', formatStarted(session.started_at)],
    ['Duration', formatDuration(session.duration_seconds)],
    ['Avg. response', `${Math.round(session.avg_response_time_ms)} ms`],
    ['Max depth reached', session.max_depth_reached.toLocaleString()],
    ['Total URLs', session.total_urls_discovered.toLocaleString()],
    ['Total failed', session.total_urls_failed.toLocaleString()],
  ];

  return (
    <div className="card">
      <div className="card-head">
        <h3>Crawl overview</h3>
        <span className="muted-pill">
          #{session.id.slice(0, 8)}
        </span>
      </div>
      <div className="overview-list">
        {rows.map(([k, v]) => (
          <div key={k} className="overview-row">
            <span>{k}</span>
            <b>{v}</b>
          </div>
        ))}
      </div>
    </div>
  );
}
