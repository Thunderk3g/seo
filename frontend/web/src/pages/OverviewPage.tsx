// OverviewPage — top-of-dashboard view for the Bajaj SEO AI system.
//
// Five blocks, top to bottom:
//   1. Headline score card — overall_score gauge + executive summary + CTA
//   2. Sub-score grid — eight cards from the latest run's sub_scores
//   3. Performance chart — clicks/impressions trend from GSC daily data
//   4. Two-column row — top opportunities | top queries
//   5. Two-column row — crawler health | top pages
//
// All five draw from `/api/v1/seo/overview/?domain=...`. When the
// backend is unreachable, every block falls back to its empty state
// instead of throwing — the page should never blank.

import { useState } from 'react';
import { Link } from 'wouter';
import PerformanceChart from '../components/seo/PerformanceChart';
import ScoreGauge from '../components/seo/ScoreGauge';
import SubScoreGrid, {
  SUB_SCORE_LABELS,
} from '../components/seo/SubScoreGrid';
import { useSeoOverview } from '../api/hooks/useSeoOverview';
import { useStartGrade } from '../api/hooks/useGrade';
import type { SeoOverview, SeoOverviewLatestRun } from '../api/seoTypes';

export default function OverviewPage() {
  const { data, isLoading, isError, refetch } = useSeoOverview();
  const startGrade = useStartGrade();
  const [bannerError, setBannerError] = useState<string | null>(null);

  function handleRunGrade() {
    setBannerError(null);
    startGrade.mutate(
      { domain: data?.domain ?? 'bajajlifeinsurance.com', sync: false },
      {
        onSuccess: () => refetch(),
        onError: (err) =>
          setBannerError(
            err instanceof Error ? err.message : 'Failed to start grading run',
          ),
      },
    );
  }

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Bajaj SEO Overview</h1>
          <div className="seo-page-sub">
            Search performance, technical health, and AI grading for{' '}
            <b>{data?.domain ?? 'bajajlifeinsurance.com'}</b>
          </div>
        </div>
      </header>

      {bannerError && <div className="seo-error">{bannerError}</div>}

      {isLoading && <div className="seo-empty">Loading overview…</div>}
      {isError && !isLoading && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server
          is running on /api/v1/seo/.
        </div>
      )}

      {data && (
        <>
          <ScoreHeadline
            run={data.latest_run}
            onRunGrade={handleRunGrade}
            running={startGrade.isPending}
          />

          <SubScoreSection run={data.latest_run} />

          <PerformanceSection data={data} />

          <div className="seo-row-2">
            <TopOpportunitiesCard run={data.latest_run} />
            <TopQueriesCard data={data} />
          </div>

          <div className="seo-row-2-balanced">
            <CrawlerHealthCard data={data} />
            <TopPagesCard data={data} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Headline ─────────────────────────────────────────────────────────────

function ScoreHeadline({
  run,
  onRunGrade,
  running,
}: {
  run: SeoOverviewLatestRun | null;
  onRunGrade: () => void;
  running: boolean;
}) {
  if (!run) {
    return (
      <div className="seo-card seo-score-card seo-elev-2">
        <div className="seo-score-gauge">
          <ScoreGauge score={null} />
        </div>
        <div className="seo-score-body">
          <p className="seo-score-summary">
            No grading run yet. Trigger one to score the site across eight
            technical and content dimensions.
          </p>
        </div>
        <div className="seo-score-cta">
          <button
            className="seo-btn"
            onClick={onRunGrade}
            disabled={running}
          >
            {running ? 'Starting…' : 'Run new grade'}
          </button>
          <Link href="/grade" className="seo-btn seo-btn-ghost">
            View grade history
          </Link>
        </div>
      </div>
    );
  }

  const score = run.overall_score ?? 0;
  const bandLabel =
    score >= 80 ? 'Healthy'
      : score >= 50 ? 'Mixed'
        : score >= 30 ? 'Needs work'
          : 'Critical';
  const bandClass =
    score >= 80 ? 'ok'
      : score >= 50 ? ''
        : score >= 30 ? 'warn'
          : 'bad';

  return (
    <div className="seo-card seo-score-card seo-elev-2">
      <div className="seo-score-gauge">
        <ScoreGauge score={run.overall_score} />
        <span className={`seo-score-band ${bandClass}`}>{bandLabel}</span>
        <div className="seo-score-meta">
          Last graded {formatRelative(run.finished_at)} · cost $
          {run.total_cost_usd.toFixed(4)}
        </div>
      </div>
      <div className="seo-score-body">
        <p className="seo-score-summary">
          {run.executive_summary ||
            'Run details are still being generated.'}
        </p>
        {run.top_action && (
          <div className="seo-score-action">{run.top_action}</div>
        )}
      </div>
      <div className="seo-score-cta">
        <button className="seo-btn" onClick={onRunGrade} disabled={running}>
          {running ? 'Starting…' : 'Run new grade'}
        </button>
        <Link href={`/grade/${run.id}`} className="seo-btn seo-btn-ghost">
          View this run
        </Link>
      </div>
    </div>
  );
}

// ── Sub-score grid ───────────────────────────────────────────────────────

function SubScoreSection({ run }: { run: SeoOverviewLatestRun | null }) {
  if (!run) return null;
  const order = [
    'technical',
    'content',
    'backlinks',
    'core_web_vitals',
    'internal_linking',
    'serp_ctr',
    'structured_data',
    'indexability',
  ] as const;
  const entries = order.map((k) => ({
    key: k,
    label: SUB_SCORE_LABELS[k],
    value: (run.sub_scores as Record<string, number | undefined>)[k],
  }));
  return <SubScoreGrid entries={entries} />;
}

// ── Performance ──────────────────────────────────────────────────────────

function PerformanceSection({ data }: { data: SeoOverview }) {
  const gsc = data.gsc;
  if (!gsc.available || !gsc.totals) {
    return (
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Search performance</h2>
        </div>
        <div className="seo-empty">
          No Search Console data available. Run{' '}
          <b>backend/scripts/gsc_pull.py</b> to populate.
        </div>
      </div>
    );
  }
  return (
    <div className="seo-card seo-perf-card">
      <div className="seo-card-head">
        <h2>Search performance</h2>
        <span className="seo-card-sub">
          Last {gsc.daily_series?.length ?? 0} days · Search Console
        </span>
      </div>
      <div className="seo-perf-totals">
        <div className="seo-perf-total">
          <span className="label">
            <span className="swatch" style={{ background: 'var(--accent)' }} />
            Clicks
          </span>
          <span className="value">{compact(gsc.totals.clicks)}</span>
        </div>
        <div className="seo-perf-total">
          <span className="label">
            <span className="swatch" style={{ background: 'var(--text-2)' }} />
            Impressions
          </span>
          <span className="value">{compact(gsc.totals.impressions)}</span>
        </div>
        <div className="seo-perf-total">
          <span className="label">Avg CTR</span>
          <span className="value">{(gsc.totals.avg_ctr * 100).toFixed(2)}%</span>
        </div>
        <div className="seo-perf-total">
          <span className="label">Avg Position</span>
          <span className="value">{gsc.totals.avg_position.toFixed(1)}</span>
        </div>
      </div>
      <PerformanceChart data={gsc.daily_series ?? []} />
    </div>
  );
}

// ── Top opportunities ────────────────────────────────────────────────────

function TopOpportunitiesCard({
  run,
}: {
  run: SeoOverviewLatestRun | null;
}) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Top opportunities</h2>
        {run && (
          <Link href={`/grade/${run.id}`} className="seo-card-sub">
            View all →
          </Link>
        )}
      </div>
      {!run || run.top_findings.length === 0 ? (
        <div className="seo-empty">No findings yet.</div>
      ) : (
        <div className="seo-finding-list">
          {run.top_findings.map((f) => (
            <div key={f.id} className="seo-finding">
              <div className={`seo-finding-bar ${f.severity}`} />
              <div>
                <div className="seo-finding-title">{f.title}</div>
                <div className="seo-finding-meta">
                  <span className={`seo-finding-chip ${f.severity}`}>
                    {f.severity}
                  </span>
                  <span className="seo-finding-agent">{f.agent}</span>
                </div>
              </div>
              <div className="seo-finding-priority">P{f.priority}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Top queries / pages ──────────────────────────────────────────────────

function TopQueriesCard({ data }: { data: SeoOverview }) {
  const rows = data.gsc.top_queries ?? [];
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Top queries</h2>
        <span className="seo-card-sub">by clicks</span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No query data.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Query</th>
              <th className="num">Clicks</th>
              <th className="num">Impr.</th>
              <th className="num">CTR</th>
              <th className="num">Pos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.query}>
                <td className="seo-cell-query" title={r.query}>{r.query}</td>
                <td className="num">{r.clicks.toLocaleString()}</td>
                <td className="num">{compact(r.impressions)}</td>
                <td className="num">{(r.ctr * 100).toFixed(1)}%</td>
                <td className="num">{r.position.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TopPagesCard({ data }: { data: SeoOverview }) {
  const rows = data.gsc.top_pages ?? [];
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Top pages</h2>
        <span className="seo-card-sub">by clicks</span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No page data.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Page</th>
              <th className="num">Clicks</th>
              <th className="num">CTR</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.page}>
                <td className="seo-cell-query" title={r.page}>{shortPath(r.page)}</td>
                <td className="num">{r.clicks.toLocaleString()}</td>
                <td className="num">{(r.ctr * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Crawler health ──────────────────────────────────────────────────────

function CrawlerHealthCard({ data }: { data: SeoOverview }) {
  const t = data.crawler.totals;
  if (!t) {
    return (
      <div className="seo-card">
        <div className="seo-card-head">
          <h2>Crawler health</h2>
        </div>
        <div className="seo-empty">No crawl data on disk.</div>
      </div>
    );
  }
  const rows = [
    ['Pages crawled', t.pages.toLocaleString()],
    ['2xx OK', t.ok.toLocaleString()],
    ['Errors', t.errors.toLocaleString()],
    ['404 Not Found', t['404'].toLocaleString()],
    ['5xx Server', t['5xx'].toLocaleString()],
    ['Orphan URLs', t.orphan.toLocaleString()],
    ['Thin content (<300 words)', t.thin_content.toLocaleString()],
    [
      'Median response time',
      `${Math.round(data.crawler.median_response_ms ?? 0)} ms`,
    ],
  ];
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Crawler health</h2>
        <span className="seo-card-sub">last crawl</span>
      </div>
      <table className="seo-table">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k as string}>
              <td>{k}</td>
              <td className="num">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function formatRelative(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '—';
  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function shortPath(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname || '/';
  } catch {
    return url;
  }
}
