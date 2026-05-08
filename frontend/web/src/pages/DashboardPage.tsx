// DashboardPage — 4-row composition over the active site's most-recent
// crawl session. Mirrors `.design-ref/project/dashboard.jsx` (lines 200–
// 238).
//
//   Row 1 .stat-row     — 5 KPI cards (StatCard with Sparkline)
//   Row 2 .dash-row-2   — SeoHealthCard | IssueDistributionCard | CrawlOverviewCard
//   Row 3 .dash-row-3   — UrlMiniTable | ActivityFeed
//   Row 4 .dash-row-4   — SystemMetricsCard | TopIssuesCard | SiteStructureMini
//
// All KPI/health data comes from `useOverview`; activity from `useActivity`;
// pages/issues/tree from their dedicated hooks consumed inside each card.
// `useSessions` is the single source of truth for `sessionId`; sparklines
// for the KPI strip are derived from the last 5 sessions' totals (newest
// last) so the trend reads left-to-right.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useActivity } from '../api/hooks/useActivity';
import { useOverview } from '../api/hooks/useOverview';
import ActivityFeed from '../components/ActivityFeed';
import HealthGauge from '../components/charts/HealthGauge';
import Meter from '../components/charts/Meter';
import SystemMetricsCard from '../components/charts/SystemMetricsCard';
import StatCard, {
  type StatCardProps,
} from '../components/dashboard/StatCard';
import IssueDistributionCard from '../components/dashboard/IssueDistributionCard';
import CrawlOverviewCard from '../components/dashboard/CrawlOverviewCard';
import TopIssuesCard from '../components/dashboard/TopIssuesCard';
import UrlMiniTable from '../components/dashboard/UrlMiniTable';
import SiteStructureMini from '../components/dashboard/SiteStructureMini';
import type {
  CrawlSessionListItem,
  OverviewKpis,
  OverviewSnapshot,
} from '../api/types';

// Pull a per-KPI sparkline series out of the recent sessions list. Sessions
// arrive newest-first; we reverse so the latest point sits on the right
// (the conventional read direction for trend lines).
function sparkSeries(
  sessions: CrawlSessionListItem[] | undefined,
  pick: (s: CrawlSessionListItem) => number,
  count = 5,
): number[] {
  if (!sessions || sessions.length === 0) return [];
  return sessions.slice(0, count).map(pick).reverse();
}

function buildKpiCards(
  kpis: OverviewKpis,
  sessions: CrawlSessionListItem[] | undefined,
): StatCardProps[] {
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
      sparkData: sparkSeries(sessions, (s) => s.total_urls_discovered),
    },
    {
      label: 'Crawled',
      value: kpis.crawled,
      color: 'var(--accent)',
      sub: pct(kpis.crawled),
      sparkData: sparkSeries(sessions, (s) => s.total_urls_crawled),
    },
    {
      label: 'Pending',
      value: kpis.pending,
      color: '#fbbf24',
      sub: pct(kpis.pending),
      dim: true,
      // No `pending`-equivalent on the list serializer; a derived
      // discovered-minus-crawled would ignore excluded/failed and be
      // misleading. Leave empty so Sparkline renders its placeholder.
      sparkData: [],
    },
    {
      label: 'Failed',
      value: kpis.failed,
      color: '#f87171',
      sub: errorRate,
      sparkData: sparkSeries(sessions, (s) => s.total_urls_failed),
    },
    {
      label: 'Excluded',
      value: kpis.excluded,
      color: '#60a5fa',
      sub: 'by robots.txt & rules',
      dim: true,
      // No `excluded` field on the list serializer — leave empty so the
      // Sparkline renders its empty placeholder.
      sparkData: [],
    },
  ];
}

const PLACEHOLDER_KPIS: StatCardProps[] = [
  { label: 'Total URLs', value: 0, color: '#a78bfa', sub: '—' },
  { label: 'Crawled', value: 0, color: 'var(--accent)', sub: '—' },
  { label: 'Pending', value: 0, color: '#fbbf24', sub: '—', dim: true },
  { label: 'Failed', value: 0, color: '#f87171', sub: '—' },
  { label: 'Excluded', value: 0, color: '#60a5fa', sub: '—', dim: true },
];

export default function DashboardPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  const session = sessionsQuery.data?.[0] ?? null;
  const sessionId = session?.id ?? null;

  const overview = useOverview(sessionId);
  const activity = useActivity({
    sessionId,
    status: session?.status ?? null,
  });

  const isLive = session?.status === 'running' || session?.status === 'pending';

  const kpiCards = overview.data
    ? buildKpiCards(overview.data.kpis, sessionsQuery.data)
    : PLACEHOLDER_KPIS;

  return (
    <div className="page-grid">
      {/* Row 1 — 5 KPI tiles */}
      <div className="row stat-row">
        {kpiCards.map((k) => (
          <StatCard key={k.label} {...k} />
        ))}
      </div>

      {/* Row 2 — Health | Issue distribution | Crawl overview */}
      <div className="row dash-row-2">
        <SeoHealthCard
          overview={overview.data ?? null}
          loading={Boolean(sessionId) && overview.isPending}
          error={Boolean(sessionId) && overview.isError}
          hasSession={Boolean(sessionId)}
        />
        <IssueDistributionCard sessionId={sessionId} />
        <CrawlOverviewCard session={session} />
      </div>

      {/* Row 3 — URL preview | Activity feed */}
      <div className="row dash-row-3">
        <UrlMiniTable sessionId={sessionId} />
        <ActivityFeed
          events={activity.data}
          isLoading={activity.isPending}
          isLive={isLive}
        />
      </div>

      {/* Row 4 — System | Top issues | Site structure */}
      <div className="row dash-row-4">
        <SystemMetricsCard />
        <TopIssuesCard sessionId={sessionId} />
        <SiteStructureMini sessionId={sessionId} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// SeoHealthCard — gauge on the left, three Meter sub-score rows on
// the right. Drops the embedded crawl-perf footer (those metrics now
// live on CrawlOverviewCard / SystemMetricsCard) and the inline
// SubScoreBar from the previous implementation in favour of the
// shared <Meter> primitive.
// ─────────────────────────────────────────────────────────────────

interface SeoHealthCardProps {
  overview: OverviewSnapshot | null;
  loading: boolean;
  error: boolean;
  hasSession: boolean;
}

const SUB_COLORS = {
  technical: 'var(--accent)',
  content: '#fbbf24',
  performance: '#60a5fa',
} as const;

function SeoHealthCard({
  overview,
  loading,
  error,
  hasSession,
}: SeoHealthCardProps) {
  return (
    <div className="card health-card">
      <div className="card-head">
        <h3>SEO Health Score</h3>
        <a className="link-btn" href="#analytics">View report</a>
      </div>

      {!hasSession && (
        <p className="text-muted" style={{ fontSize: 12 }}>
          No crawl sessions yet — start one from the topbar.
        </p>
      )}
      {hasSession && loading && (
        <p className="text-muted" style={{ fontSize: 12 }}>Loading overview…</p>
      )}
      {hasSession && error && (
        <p style={{ color: '#f87171', fontSize: 12 }}>
          Failed to load overview.
        </p>
      )}

      {overview && (
        <div className="health-body">
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <HealthGauge
              score={overview.health.score}
              band={overview.health.band}
              size={160}
              thickness={14}
            />
          </div>
          <div className="health-subs">
            <SubScoreRow
              label="Technical SEO"
              value={overview.health.sub_scores?.technical ?? 0}
              color={SUB_COLORS.technical}
            />
            <SubScoreRow
              label="Content SEO"
              value={overview.health.sub_scores?.content ?? 0}
              color={SUB_COLORS.content}
            />
            <SubScoreRow
              label="Performance"
              value={overview.health.sub_scores?.performance ?? 0}
              color={SUB_COLORS.performance}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function SubScoreRow({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  const safe = Math.max(0, Math.min(100, value));
  return (
    <div className="health-sub">
      <div className="health-sub-row">
        <span>{label}</span>
        <b>
          {safe}
          <span className="text-muted">/100</span>
        </b>
      </div>
      <Meter value={safe} color={color} height={5} />
    </div>
  );
}
