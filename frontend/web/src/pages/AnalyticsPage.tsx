// AnalyticsPage — four chart cards (status / depth / response-time / content-type)
// for the active site's most-recent crawl session.
//
// Backed by GET /sessions/:id/analytics/ via useAnalytics. Layout ported from
// .design-ref/project/pages.jsx AnalyticsPage: two `.row.analytics-row` rows,
// each with two cards. Donuts use MiniDonut + a small legend; bar charts use
// MiniBars. No buttons on this screen per spec §5.4.5.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useAnalytics } from '../api/hooks/useAnalytics';
import MiniDonut from '../components/charts/MiniDonut';
import MiniBars from '../components/charts/MiniBars';
import type {
  AnalyticsContentTypeEntry,
  AnalyticsStatusEntry,
} from '../api/types';

// Backend doesn't ship a `color` for content-type entries — assign here.
const CONTENT_TYPE_COLORS: Record<AnalyticsContentTypeEntry['label'], string> = {
  html: '#6ee7b7',
  image: '#f472b6',
  css: '#a78bfa',
  js: '#fbbf24',
  font: '#60a5fa',
  document: '#94a3b8',
  other: '#475569',
};

interface LegendItem {
  label: string;
  count: number;
  color: string;
}

function Legend({ items, total }: { items: LegendItem[]; total: number }) {
  if (items.length === 0) {
    return <div className="text-muted" style={{ fontSize: 12 }}>No data</div>;
  }
  return (
    <div className="legend">
      {items.map((it) => {
        const pct = total > 0 ? (it.count / total) * 100 : 0;
        return (
          <div key={it.label} className="legend-row">
            <span className="dot-sm" style={{ background: it.color }} />
            <span className="legend-label">{it.label}</span>
            <span className="legend-value">{it.count.toLocaleString()}</span>
            <span className="legend-pct">{pct.toFixed(1)}%</span>
          </div>
        );
      })}
    </div>
  );
}

export default function AnalyticsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Most-recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;

  const analytics = useAnalytics(session?.id ?? null);

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (!session) return 'No crawl sessions yet — start one from the topbar';
    return `Latest session: ${session.website_domain} • ${session.status}`;
  })();

  return (
    <div className="page-grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Analytics</h1>
          <div className="page-subtitle">{subtitle}</div>
        </div>
      </div>

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to see crawl analytics.
          </p>
        </div>
      )}

      {activeSiteId && !session && !sessionsQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No crawl sessions exist for this site yet. Start one from the
            topbar.
          </p>
        </div>
      )}

      {session && analytics.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">Loading analytics…</p>
        </div>
      )}

      {session && analytics.isError && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p style={{ color: 'var(--error)' }}>
            Failed to load analytics
            {analytics.error instanceof Error
              ? `: ${analytics.error.message}`
              : '.'}
          </p>
        </div>
      )}

      {session && analytics.data && (
        <AnalyticsCharts data={analytics.data} />
      )}
    </div>
  );
}

function AnalyticsCharts({
  data,
}: {
  data: import('../api/types').AnalyticsCharts;
}) {
  const total = data.total_pages;

  const statusItems: LegendItem[] = data.status_distribution.map(
    (s: AnalyticsStatusEntry) => ({
      label: s.label,
      count: s.count,
      color: s.color,
    }),
  );

  const contentTypeItems: LegendItem[] = data.content_type_distribution.map(
    (c) => ({
      label: c.label,
      count: c.count,
      color: CONTENT_TYPE_COLORS[c.label] ?? CONTENT_TYPE_COLORS.other,
    }),
  );

  // Depth bars — order by depth ascending; show "/" for depth 0.
  const depthEntries = [...data.depth_distribution]
    .sort((a, b) => a.depth - b.depth)
    .map((d) => ({
      label: d.depth === 0 ? '/' : `d${d.depth}`,
      count: d.count,
    }));

  // Response-time bars — preserve backend order (already sorted by bucket).
  const responseEntries = data.response_time_histogram.map((r) => ({
    label: r.bucket,
    count: r.count,
  }));

  return (
    <>
      <div className="row analytics-row">
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <div className="card-head">
            <h3>Status codes</h3>
          </div>
          <div className="analytics-chart-body">
            <MiniDonut
              entries={statusItems}
              total={total}
              size={170}
              thickness={18}
              centerLabel="URLs"
            />
            <Legend items={statusItems} total={total} />
          </div>
        </div>

        <div className="card" style={{ padding: 'var(--pad)' }}>
          <div className="card-head">
            <h3>Crawl depth</h3>
          </div>
          <MiniBars entries={depthEntries} height={210} />
        </div>
      </div>

      <div className="row analytics-row">
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <div className="card-head">
            <h3>Response time</h3>
          </div>
          <MiniBars entries={responseEntries} height={210} />
        </div>

        <div className="card" style={{ padding: 'var(--pad)' }}>
          <div className="card-head">
            <h3>Content types</h3>
          </div>
          <div className="analytics-chart-body">
            <MiniDonut
              entries={contentTypeItems}
              total={total}
              size={170}
              thickness={18}
              centerLabel="URLs"
            />
            <Legend items={contentTypeItems} total={total} />
          </div>
        </div>
      </div>
    </>
  );
}
