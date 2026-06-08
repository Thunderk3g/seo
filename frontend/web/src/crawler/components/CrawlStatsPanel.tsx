/**
 * CrawlStatsPanel — Googlebot's own crawl behaviour on the site, from the
 * GSC "Crawl stats" report (Settings → Crawl stats → Export).
 *
 * IMPORTANT: this report is NOT available via the Search Console API — it
 * is export-only. The backend serves the parsed CSV bundle the operator
 * drops into backend/data/gsc_crawl_stats/. When nothing is on disk yet we
 * render a "drop your export here" empty state.
 *
 * Shows: total crawl requests, avg response time, total download, a daily
 * request sparkline, and the response-code / file-type / Googlebot-type /
 * purpose mixes — plus host status. Bajaj-blue design system primitives.
 */
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { crawlerApi, type GscCrawlStatsRatioRow } from '../api';

function fmtBytes(n: number | undefined): string {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function CrawlStatsPanel() {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['crawler', 'gsc-crawl-stats'],
    queryFn: () => crawlerApi.crawlStats(),
    staleTime: 5 * 60_000,
  });

  return (
    <div className="bajaj-ui">
      <Card className="mb-4 shadow-e2">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle>
              Google Crawl Stats
              <span className="ml-2 text-xs font-normal text-brand-text-4">
                Googlebot activity · export-only (no API)
              </span>
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              disabled={isFetching}
              onClick={() => {
                // POST flushes the server cache, then re-read.
                crawlerApi.crawlStats({ refresh: true }).finally(() => refetch());
              }}
            >
              {isFetching ? 'Refreshing…' : 'Refresh export'}
            </Button>
          </div>
        </CardHeader>

        <CardContent>
          {isLoading && (
            <div className="text-sm text-brand-text-3">Loading crawl stats…</div>
          )}

          {isError && (
            <div className="text-sm text-severity-error">
              Crawl stats unavailable: {error instanceof Error ? error.message : 'unknown error'}
            </div>
          )}

          {data && !data.present && (
            <div className="rounded-md border border-dashed border-brand-border bg-brand-surface-2 px-4 py-6 text-sm text-brand-text-3">
              <div className="mb-1 font-semibold text-brand-text">No Crawl Stats export found</div>
              The GSC Crawl Stats report can't be pulled via API. Export it from
              Search Console (Settings → Crawl stats → Export) and drop the CSVs into{' '}
              <span className="font-mono text-brand-text">{data.source_dir || 'data/gsc_crawl_stats/'}</span>,
              then click <span className="font-semibold">Refresh export</span>.
            </div>
          )}

          {data && data.present && data.totals && (
            <>
              <div className="mb-4 flex flex-wrap items-baseline gap-6">
                <Headline label="Total crawl requests" value={data.totals.total_requests.toLocaleString()} />
                <Headline label="Avg response time" value={`${data.totals.avg_response_time_ms} ms`} />
                <Headline label="Total download" value={fmtBytes(data.totals.total_download_bytes)} />
                <Headline
                  label="Window"
                  value={`${data.totals.days} days`}
                  sub={`${data.totals.date_start} → ${data.totals.date_end}`}
                />
              </div>

              {data.series && data.series.length > 1 && (
                <Sparkline points={data.series.map((s) => s.requests)} />
              )}

              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                <RatioBars title="By response" rows={data.by_response} accent="status" />
                <RatioBars title="By file type" rows={data.by_file_type} />
                <RatioBars title="By Googlebot type" rows={data.by_googlebot_type} />
                <RatioBars title="By purpose" rows={data.by_purpose} />
              </div>

              {data.hosts && data.hosts.length > 0 && (
                <div className="mt-5">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                    Host status
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {data.hosts.map((h) => (
                      <div
                        key={h.host}
                        className="flex items-center gap-2 rounded-md bg-brand-surface-2 px-3 py-2 text-sm"
                      >
                        <span className="font-mono text-brand-text">{h.host}</span>
                        <span className="text-brand-text-3">{h.requests.toLocaleString()} req</span>
                        <Badge variant={/no problem/i.test(h.status) ? 'success' : 'warning'}>
                          {h.status || 'unknown'}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {data.exported_at && (
                <div className="mt-4 text-xs text-brand-text-4">
                  Export last updated {new Date(data.exported_at).toLocaleString()}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Headline({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold leading-none text-brand-text">{value}</div>
      <div className="mt-1 text-xs text-brand-text-3">{label}</div>
      {sub && <div className="text-xs text-brand-text-4">{sub}</div>}
    </div>
  );
}

// Status-code coloring so 200/304 read green, 3xx amber, 4xx/5xx hot.
// Matched against GSC's response labels, e.g. "OK (200)",
// "Not modified (304)", "Moved permanently (301)", "Not found (404)",
// "Server error (5XX)", "Page timeout".
function statusTone(label: string): string {
  if (/^ok|\b2\d\d\b|not modified|304/i.test(label)) return 'bg-severity-success';
  if (/404|not found|\b4\d\d\b|forbidden|unauthorized/i.test(label)) return 'bg-severity-error';
  if (/\b30[12]\b|moved|redirect/i.test(label)) return 'bg-severity-warning';
  if (/\b5\d\d\b|5xx|server error|timeout|could not/i.test(label)) return 'bg-severity-error';
  return 'bg-brand-primary';
}

function RatioBars({
  title,
  rows,
  accent,
}: {
  title: string;
  rows?: GscCrawlStatsRatioRow[];
  accent?: 'status';
}) {
  if (!rows || rows.length === 0) return null;
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
        {title}
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex items-center justify-between text-xs">
              <span className="text-brand-text">{r.label}</span>
              <span className="text-brand-text-3">{r.pct.toFixed(1)}%</span>
            </div>
            <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded bg-brand-surface-2">
              <div
                className={`h-full rounded ${accent === 'status' ? statusTone(r.label) : 'bg-brand-primary'}`}
                style={{ width: `${Math.max(2, Math.min(100, r.pct))}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Lightweight inline SVG sparkline of daily request volume — no chart dep.
function Sparkline({ points }: { points: number[] }) {
  const W = 600;
  const H = 48;
  const max = Math.max(...points, 1);
  const min = Math.min(...points);
  const span = max - min || 1;
  const step = points.length > 1 ? W / (points.length - 1) : W;
  const path = points
    .map((p, i) => {
      const x = i * step;
      const y = H - ((p - min) / span) * (H - 4) - 2;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
        Daily crawl requests
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-12 w-full">
        <path d={path} fill="none" stroke="var(--primary, #0046be)" strokeWidth={1.5} />
      </svg>
    </div>
  );
}
