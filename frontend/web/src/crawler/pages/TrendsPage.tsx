/**
 * TrendsPage — `/trends`.
 *
 * Daily Health Score over time, with overlaid error / warning / notice
 * counts. Reads MetricSnapshot rows via /api/v1/crawler/trends.
 *
 * Phase 5a ships a custom SVG line chart (the codebase pattern; we
 * don't pull in a chart library since the existing dashboard uses
 * hand-rolled SVGs everywhere). Once we have 30+ days of snapshots the
 * line is meaningful. Below 7 days we show a "collecting data"
 * placeholder.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { crawlerApi } from '../api';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';

type Window = 30 | 90 | 365;

export default function TrendsPage() {
  const [window, setWindow] = useState<Window>(90);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'trends', window],
    queryFn: () => crawlerApi.trends({ window }),
    staleTime: 5 * 60_000,
  });

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-brand-text">Trends</h1>
          <p className="mt-1 text-sm text-brand-text-3">
            Daily Health Score + issue counts over time. Populated by the
            nightly snapshot task; force a refresh with
            <code className="ml-1 rounded bg-brand-surface-2 px-1.5 py-0.5 font-mono text-xs">
              python manage.py snapshot_metrics
            </code>
            .
          </p>
        </div>
        <WindowSwitcher value={window} onChange={setWindow} />
      </header>

      {isLoading && (
        <Card><CardContent className="py-4 text-sm text-brand-text-3">Loading snapshots…</CardContent></Card>
      )}

      {isError && (
        <Card className="border-severity-error">
          <CardContent className="py-4 text-severity-error">
            {error instanceof Error ? error.message : 'Failed to load trends.'}
          </CardContent>
        </Card>
      )}

      {data && data.snapshot_count === 0 && (
        <Card>
          <CardContent className="py-8 text-center">
            <div className="text-sm text-brand-text">
              No snapshots recorded yet.
            </div>
            <div className="mt-2 text-xs text-brand-text-3">
              Run <code className="font-mono">python manage.py snapshot_metrics</code> daily, or wire the Celery beat task.
            </div>
          </CardContent>
        </Card>
      )}

      {data && data.snapshot_count > 0 && (
        <>
          <SnapshotChart snapshots={data.snapshots} />
          <SnapshotTable snapshots={data.snapshots} />
        </>
      )}
    </div>
  );
}

function WindowSwitcher({
  value,
  onChange,
}: {
  value: Window;
  onChange: (w: Window) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-brand-border bg-card p-0.5 shadow-e1">
      {[30, 90, 365].map((w) => (
        <button
          key={w}
          type="button"
          onClick={() => onChange(w as Window)}
          className={
            'rounded-sm px-3 py-1 text-xs font-medium transition-colors ' +
            (w === value
              ? 'bg-brand-accent text-white'
              : 'text-brand-text-3 hover:text-brand-text')
          }
        >
          {w} days
        </button>
      ))}
    </div>
  );
}

function SnapshotChart({
  snapshots,
}: {
  snapshots: Array<{
    recorded_date: string;
    health_score: number | null;
    errors: number;
    warnings: number;
  }>;
}) {
  // We render a single-axis line chart for Health Score and a stacked
  // bar overlay for errors/warnings. Pure SVG, no chart library —
  // mirrors the lattice.css conventions.
  const width = 880;
  const height = 280;
  const padding = { top: 24, right: 60, bottom: 36, left: 48 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const scoreSeries = useMemo(
    () => snapshots.map((s, i) => ({
      x: i,
      y: s.health_score ?? 0,
      date: s.recorded_date,
    })),
    [snapshots],
  );

  if (scoreSeries.length < 2) {
    return (
      <Card className="mb-4">
        <CardContent className="py-8 text-center text-sm text-brand-text-3">
          Need at least 2 snapshots to plot a trend. Today's snapshot is
          recorded; check back tomorrow or after the next nightly run.
        </CardContent>
      </Card>
    );
  }

  const maxScore = 100;
  const xStep = innerW / Math.max(1, scoreSeries.length - 1);
  const linePath = scoreSeries
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${padding.left + p.x * xStep} ${padding.top + innerH - (p.y / maxScore) * innerH}`)
    .join(' ');
  const areaPath = `${linePath} L ${padding.left + (scoreSeries.length - 1) * xStep} ${padding.top + innerH} L ${padding.left} ${padding.top + innerH} Z`;

  const currentScore = scoreSeries[scoreSeries.length - 1]?.y ?? 0;
  const firstScore = scoreSeries[0]?.y ?? 0;
  const delta = currentScore - firstScore;

  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Health Score over time</CardTitle>
          <Badge variant={delta >= 0 ? 'success' : 'error'}>
            {delta >= 0 ? '+' : ''}{delta} pts
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="xMidYMid meet">
          {/* Y-axis grid lines + labels at 0/25/50/75/100 */}
          {[0, 25, 50, 75, 100].map((tick) => {
            const y = padding.top + innerH - (tick / maxScore) * innerH;
            return (
              <g key={tick}>
                <line
                  x1={padding.left}
                  x2={width - padding.right}
                  y1={y}
                  y2={y}
                  stroke="rgba(0,44,110,0.06)"
                />
                <text
                  x={padding.left - 8}
                  y={y + 4}
                  textAnchor="end"
                  fontSize="10"
                  fill="rgba(0,44,110,0.55)"
                >
                  {tick}
                </text>
              </g>
            );
          })}

          {/* Area fill under the line */}
          <path d={areaPath} fill="rgba(0,114,206,0.10)" />

          {/* Line */}
          <path d={linePath} fill="none" stroke="#0072ce" strokeWidth={2} />

          {/* Data points */}
          {scoreSeries.map((p) => (
            <circle
              key={p.date}
              cx={padding.left + p.x * xStep}
              cy={padding.top + innerH - (p.y / maxScore) * innerH}
              r={3}
              fill="#0072ce"
            />
          ))}

          {/* X-axis date labels — first / mid / last to avoid overlap */}
          {[0, Math.floor(scoreSeries.length / 2), scoreSeries.length - 1].map((i) => (
            <text
              key={`x-${i}`}
              x={padding.left + i * xStep}
              y={height - 12}
              textAnchor="middle"
              fontSize="10"
              fill="rgba(0,44,110,0.55)"
            >
              {scoreSeries[i].date}
            </text>
          ))}
        </svg>
      </CardContent>
    </Card>
  );
}

function SnapshotTable({
  snapshots,
}: {
  snapshots: Array<{
    recorded_date: string;
    engine: string;
    health_score: number | null;
    health_tier: string;
    errors: number;
    warnings: number;
    notices: number;
    pages_ok: number;
    pages_attempted: number;
    pagerank_orphan_count: number;
    near_dup_cluster_count: number;
  }>;
}) {
  // Show most-recent at the top
  const reversed = useMemo(() => [...snapshots].reverse().slice(0, 30), [snapshots]);
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Recent snapshots</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-brand-border text-left">
              <tr>
                <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">Date</th>
                <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">Engine</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Score</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Errors</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Warnings</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Notices</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Pages OK</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Orphans</th>
                <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Dup clusters</th>
              </tr>
            </thead>
            <tbody>
              {reversed.map((s, i) => (
                <tr
                  key={`${s.recorded_date}-${s.engine}`}
                  className={`border-t border-brand-border ${i % 2 === 1 ? 'bg-brand-surface-2/50' : ''}`}
                >
                  <td className="px-2 py-2 text-brand-text">{s.recorded_date}</td>
                  <td className="px-2 py-2 text-brand-text-2">{s.engine}</td>
                  <td className="px-2 py-2 text-right tabular-nums font-semibold text-brand-text">
                    {s.health_score ?? '—'}{' '}
                    {s.health_tier && (
                      <span className="text-xs font-normal text-brand-text-3">
                        {s.health_tier}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-severity-error">{s.errors.toLocaleString()}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-severity-warning">{s.warnings.toLocaleString()}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-severity-notice">{s.notices.toLocaleString()}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{s.pages_ok.toLocaleString()}/{s.pages_attempted.toLocaleString()}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{s.pagerank_orphan_count.toLocaleString()}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{s.near_dup_cluster_count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {snapshots.length > 30 && (
          <div className="mt-2 text-xs text-brand-text-3">
            Showing 30 most recent of {snapshots.length}.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
