// DashboardPage.tsx — Day 0 placeholder.
// Renders the 5-card KPI strip from .design-ref/project/dashboard.jsx with
// hardcoded numbers from data.js (lumen.travel sample). All other dashboard
// cards (SEO health, issue donut, activity feed, etc.) are still on the
// design-ref but live behind chart components we haven't ported yet.
//
// TODO: replace with real data via TanStack Query (Day 5)

interface KpiCard {
  label: string;
  value: number;
  color: string;
  sub: string;
  dim?: boolean;
}

// Numbers lifted verbatim from .design-ref/project/app.jsx (initial crawl state)
// and .design-ref/project/dashboard.jsx (StatCard sub-text formulas).
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
        {/* TODO: Sparkline (Day 1+ — needs charts/Sparkline port). */}
        <div style={{ width: 110, height: 36 }} aria-hidden="true" />
      </div>
      <div className={'stat-sub ' + (dim ? 'dim' : '')}>{sub}</div>
    </div>
  );
}

export default function DashboardPage() {
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
            Gauge, donut, crawl overview, activity feed, system metrics, top
            issues and site-structure cards arrive in Days 1–4 once their
            backing endpoints land. Layout shell is live now.
          </p>
        </div>
      </div>
    </div>
  );
}
