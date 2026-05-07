// DashboardPage — KPI strip + live activity feed for the active site's
// most-recent crawl session.
//
// KPIs are still placeholder values (Day 5 will wire SnapshotService /
// /sessions/:id/overview/). The Activity feed (right column) is real:
// `useActivity` polls `/sessions/:id/activity/` every 1.5s while the session
// is running and renders a rolling 14-row buffer via <ActivityFeed/>.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useActivity } from '../api/hooks/useActivity';
import ActivityFeed from '../components/ActivityFeed';

interface KpiCard {
  label: string;
  value: number;
  color: string;
  sub: string;
  dim?: boolean;
}

// Numbers lifted verbatim from .design-ref/project/app.jsx (initial crawl state)
// and .design-ref/project/dashboard.jsx (StatCard sub-text formulas). These
// remain hardcoded until Day 5 wires /sessions/:id/overview/ for the SEO
// Health gauge / KPI strip.
const KPIS: KpiCard[] = [
  { label: 'Total URLs', value: 2310, color: '#a78bfa', sub: '+18.7% vs last crawl' },
  { label: 'Crawled', value: 1842, color: 'var(--accent)', sub: '79.7% of total' },
  { label: 'Pending', value: 423, color: '#fbbf24', sub: '18.3% of total', dim: true },
  { label: 'Failed', value: 47, color: '#f87171', sub: '2.55% error rate' },
  { label: 'Excluded', value: 312, color: '#60a5fa', sub: 'by robots.txt & rules', dim: true },
];

function StatCard({ label, value, color, sub, dim }: KpiCard) {
  return (
    <div className="card stat-card">
      <div className="stat-head">
        <div className="stat-dot" style={{ background: color }} />
        <span className="stat-label">{label}</span>
      </div>
      <div className="stat-value-row">
        <div className="stat-value">{value.toLocaleString()}</div>
        <div style={{ width: 110, height: 36 }} aria-hidden="true" />
      </div>
      <div className={'stat-sub ' + (dim ? 'dim' : '')}>{sub}</div>
    </div>
  );
}

export default function DashboardPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Most-recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;

  const activity = useActivity({
    sessionId: session?.id ?? null,
    status: session?.status ?? null,
  });

  const isLive = session?.status === 'running' || session?.status === 'pending';

  return (
    <div className="page-grid">
      <div className="row stat-row">
        {KPIS.map((k) => (
          <StatCard key={k.label} {...k} />
        ))}
      </div>

      <div className="row dash-row-2">
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <div className="card-head">
            <h3>SEO Health Score</h3>
          </div>
          <p className="text-muted">
            Gauge, donut, crawl overview, system metrics, top issues and
            site-structure cards arrive in Days 3–5 once their backing
            endpoints land. Live activity feed is wired now (right) — start a
            crawl from the topbar to populate it.
          </p>
        </div>

        <ActivityFeed
          events={activity.data}
          isLoading={activity.isPending}
          isLive={isLive}
        />
      </div>
    </div>
  );
}
