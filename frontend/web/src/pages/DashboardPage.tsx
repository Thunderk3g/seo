// DashboardPage — KPI strip + SEO Health gauge + system metrics + live
// activity feed for the active site's most-recent crawl session.
//
// Day 5: KPIs and the SEO Health Score card are now real. The KPI cards
// read from /sessions/<id>/overview/ via `useOverview`, the health gauge
// is rendered from `data.health`, and the system-metrics card uses
// `data.system_metrics`. Activity feed (right column) remains real and
// polls every 1.5s while the session is running.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useActivity } from '../api/hooks/useActivity';
import { useOverview } from '../api/hooks/useOverview';
import ActivityFeed from '../components/ActivityFeed';
import HealthGauge from '../components/charts/HealthGauge';
import SystemMetricsCard from '../components/charts/SystemMetricsCard';
import type { OverviewKpis } from '../api/types';

interface KpiCard {
  label: string;
  value: number;
  color: string;
  sub: string;
  dim?: boolean;
}

// Map the server-side `kpis` payload into the design's 5-card layout.
// Colors and ordering match the original hardcoded KPIS array verbatim
// so the visual stays stable; only the numbers (and sub-text) move to
// being computed from real data.
function buildKpiCards(kpis: OverviewKpis): KpiCard[] {
  const total = kpis.total_urls;
  const pct = (n: number) =>
    total > 0 ? `${((n / total) * 100).toFixed(1)}% of total` : '—';
  const errorRate =
    kpis.crawled > 0
      ? `${((kpis.failed / kpis.crawled) * 100).toFixed(2)}% error rate`
      : '—';

  return [
    {
      label: 'Total URLs',
      value: kpis.total_urls,
      color: '#a78bfa',
      sub: 'discovered in this session',
    },
    {
      label: 'Crawled',
      value: kpis.crawled,
      color: 'var(--accent)',
      sub: pct(kpis.crawled),
    },
    {
      label: 'Pending',
      value: kpis.pending,
      color: '#fbbf24',
      sub: pct(kpis.pending),
      dim: true,
    },
    {
      label: 'Failed',
      value: kpis.failed,
      color: '#f87171',
      sub: errorRate,
    },
    {
      label: 'Excluded',
      value: kpis.excluded,
      color: '#60a5fa',
      sub: 'by robots.txt & rules',
      dim: true,
    },
  ];
}

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

// Render the five KPI cards as zero-valued placeholders while the
// overview query is loading or hasn't fired yet — keeps the layout
// stable instead of collapsing to a spinner.
const PLACEHOLDER_KPIS: KpiCard[] = [
  { label: 'Total URLs', value: 0, color: '#a78bfa', sub: '—' },
  { label: 'Crawled', value: 0, color: 'var(--accent)', sub: '—' },
  { label: 'Pending', value: 0, color: '#fbbf24', sub: '—', dim: true },
  { label: 'Failed', value: 0, color: '#f87171', sub: '—' },
  { label: 'Excluded', value: 0, color: '#60a5fa', sub: '—', dim: true },
];

export default function DashboardPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Most-recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;
  const sessionId = session?.id ?? null;

  const overview = useOverview(sessionId);
  const activity = useActivity({
    sessionId,
    status: session?.status ?? null,
  });

  const isLive = session?.status === 'running' || session?.status === 'pending';

  const kpiCards = overview.data
    ? buildKpiCards(overview.data.kpis)
    : PLACEHOLDER_KPIS;

  return (
    <div className="page-grid">
      <div className="row stat-row">
        {kpiCards.map((k) => (
          <StatCard key={k.label} {...k} />
        ))}
      </div>

      <div className="row dash-row-2">
        <div
          className="card"
          style={{
            padding: 'var(--pad)',
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
          }}
        >
          <div className="card-head">
            <h3>SEO Health Score</h3>
          </div>

          {/* Loading and error states mirror the IssuesPage convention. */}
          {!sessionId && (
            <p className="text-muted">
              No crawl sessions yet — start one from the topbar.
            </p>
          )}
          {sessionId && overview.isPending && (
            <p className="text-muted">Loading overview…</p>
          )}
          {sessionId && overview.isError && (
            <p style={{ color: 'var(--error, #f87171)' }}>
              Failed to load overview
              {overview.error instanceof Error
                ? `: ${overview.error.message}`
                : '.'}
            </p>
          )}

          {overview.data && (
            <>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  paddingTop: 6,
                }}
              >
                <HealthGauge
                  score={overview.data.health.score}
                  band={overview.data.health.band}
                />
              </div>

              {/* Spec §5.4.1 — three sub-scores rendered as compact bars
                  below the gauge. Optional for backwards-compat: only
                  render when the backend supplies sub_scores. */}
              {overview.data.health.sub_scores && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: 8,
                    marginTop: 4,
                  }}
                >
                  <SubScoreBar
                    label="Technical"
                    value={overview.data.health.sub_scores.technical}
                  />
                  <SubScoreBar
                    label="Content"
                    value={overview.data.health.sub_scores.content}
                  />
                  <SubScoreBar
                    label="Performance"
                    value={overview.data.health.sub_scores.performance}
                  />
                </div>
              )}

              <ul
                style={{
                  listStyle: 'none',
                  padding: 0,
                  margin: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                  fontSize: 12,
                }}
              >
                {overview.data.health.reasons.map((r) => (
                  <li
                    key={r.label}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: 12,
                      color: 'var(--text-2)',
                    }}
                  >
                    <span>{r.label}</span>
                    <span
                      className="num"
                      style={{
                        color:
                          r.delta < 0
                            ? '#f87171'
                            : r.delta > 0
                              ? '#6ee7b7'
                              : 'var(--text-3)',
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {r.delta > 0 ? '+' : ''}
                      {r.delta}
                    </span>
                  </li>
                ))}
              </ul>

              {/* Crawl performance metrics — about the crawl itself
                  (response times, depth, issue density). Distinct from
                  the host-level System Metrics card below the row, which
                  shows CPU/memory/Redis queue depth/Celery RPS. */}
              <div
                style={{
                  borderTop: '1px solid var(--border, rgba(255,255,255,0.08))',
                  paddingTop: 12,
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '8px 16px',
                  fontSize: 12,
                }}
              >
                <SystemMetric
                  label="Avg response"
                  value={`${Math.round(overview.data.system_metrics.avg_response_time_ms)}ms`}
                />
                <SystemMetric
                  label="p95 response"
                  value={
                    overview.data.system_metrics.p95_response_time_ms != null
                      ? `${Math.round(overview.data.system_metrics.p95_response_time_ms)}ms`
                      : '—'
                  }
                />
                <SystemMetric
                  label="Median depth"
                  value={overview.data.system_metrics.median_depth.toLocaleString()}
                />
                <SystemMetric
                  label="Max depth"
                  value={overview.data.system_metrics.max_depth_reached.toLocaleString()}
                />
                <SystemMetric
                  label="Pages with issues"
                  value={overview.data.system_metrics.pages_with_issues.toLocaleString()}
                />
              </div>
            </>
          )}
        </div>

        <ActivityFeed
          events={activity.data}
          isLoading={activity.isPending}
          isLive={isLive}
        />
      </div>

      <div className="row">
        <SystemMetricsCard />
      </div>
    </div>
  );
}

// Compact sub-score row: label + a horizontal bar + numeric value.
// Color matches the SEO Health gauge bands for a visual link with the
// top score. Bar is filled to ``value%`` (0..100, clamped defensively).
function SubScoreBar({ label, value }: { label: string; value: number }) {
  const safe = Math.max(0, Math.min(100, value));
  const color =
    safe >= 80 ? '#6ee7b7' : safe >= 50 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 11,
          color: 'var(--text-3)',
        }}
      >
        <span>{label}</span>
        <span
          className="num"
          style={{
            color: 'var(--text-1)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {safe}
        </span>
      </div>
      <div
        style={{
          height: 4,
          borderRadius: 2,
          background: 'rgba(255,255,255,0.06)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${safe}%`,
            height: '100%',
            background: color,
            transition: 'width 200ms ease',
          }}
        />
      </div>
    </div>
  );
}

function SystemMetric({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}
    >
      <span style={{ color: 'var(--text-3)' }}>{label}</span>
      <span
        className="num"
        style={{
          color: 'var(--text-1)',
          fontWeight: 500,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </span>
    </div>
  );
}
