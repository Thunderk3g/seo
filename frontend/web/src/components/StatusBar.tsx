// StatusBar.tsx — bottom status footer for the Lattice shell.
//
// Polish pass: ports the multi-segment row from .design-ref/project/app.jsx
// (lines 147–157) and wires it to real data:
//   - "Connected to LatticeBot/2.4" — static brand identifier
//   - Last crawl   — most recent session's started_at, formatted as
//                    "May 6 13:30 IST" (Asia/Kolkata)
//   - Crawl type   — most recent session's session_type
//   - User agent   — useSettings(activeSiteId).custom_user_agent or default
//   - System health — derived from useSystemMetrics: redis.connected &&
//                     celery.workers_online >= 1 → "All systems operational",
//                     otherwise "Degraded — check Redis/Celery"
//
// When data is unavailable (no active site, no sessions yet, query
// loading/errored) the segments fall back to "—" so the dot-separator
// rhythm stays intact instead of collapsing.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useSettings } from '../api/hooks/useSettings';
import { useSystemMetrics } from '../api/hooks/useSystemMetrics';
import type { CrawlSessionListItem, SessionType } from '../api/types';

const DEFAULT_USER_AGENT = 'LatticeBot/2.4';

const SESSION_TYPE_LABELS: Record<SessionType, string> = {
  scheduled: 'Scheduled',
  on_demand: 'On-demand',
  url_inspection: 'URL inspection',
};

function formatLastCrawl(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  // Manual format keeps the "MMM D HH:mm IST" shape from the design ref
  // without pulling a date library.
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(d);
  const month = parts.find((p) => p.type === 'month')?.value ?? '';
  const day = parts.find((p) => p.type === 'day')?.value ?? '';
  const hour = parts.find((p) => p.type === 'hour')?.value ?? '';
  const minute = parts.find((p) => p.type === 'minute')?.value ?? '';
  return `${month} ${day} ${hour}:${minute} IST`;
}

function formatSessionType(t: SessionType | undefined): string {
  if (!t) return '—';
  return SESSION_TYPE_LABELS[t] ?? t;
}

export default function StatusBar() {
  const { activeSiteId } = useActiveSite();
  const sessions = useSessions(activeSiteId);
  const settings = useSettings(activeSiteId);
  const systemMetrics = useSystemMetrics();

  const latest: CrawlSessionListItem | null = sessions.data?.[0] ?? null;
  const lastCrawl = formatLastCrawl(latest?.started_at ?? null);
  const crawlType = formatSessionType(latest?.session_type);

  const customUa = settings.data?.custom_user_agent?.trim() ?? '';
  const userAgent = customUa.length > 0 ? customUa : DEFAULT_USER_AGENT;

  // System health: only commit to a verdict once the metrics query has
  // returned. While loading/errored we render the neutral "—" segment so
  // we don't flash "Degraded" on a transient empty state.
  let healthLabel = '—';
  let healthClass = 'status-online';
  if (systemMetrics.data) {
    const ok =
      systemMetrics.data.redis.connected &&
      systemMetrics.data.celery.workers_online >= 1;
    healthLabel = ok ? 'All systems operational' : 'Degraded — check Redis/Celery';
    healthClass = ok ? 'status-online' : 'status-online status-degraded';
  }

  return (
    <footer className="status-bar">
      <span>
        <span className="status-dot" /> Connected to {DEFAULT_USER_AGENT}
      </span>
      <span className="text-muted">·</span>
      <span>Last crawl {lastCrawl}</span>
      <span className="text-muted">·</span>
      <span>
        Crawl type <b>{crawlType}</b>
      </span>
      <span className="text-muted">·</span>
      <span>
        User agent <b className="mono">{userAgent}</b>
      </span>
      <span style={{ flex: 1 }} />
      <span className={healthClass}>
        <span className="status-dot" /> {healthLabel}
      </span>
    </footer>
  );
}
