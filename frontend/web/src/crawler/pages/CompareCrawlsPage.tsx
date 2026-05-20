/**
 * CompareCrawlsPage — `/compare`.
 *
 * SEMrush-style snapshot diff. Without query params, picks the two
 * most-recent CrawlSnapshot rows. Allows the operator to validate
 * "did the fix work?" by comparing today's crawl against last
 * week's, OR validate parity between the legacy + Scrapy engines
 * during the 30-day migration soak.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearch } from 'wouter';
import { crawlerApi } from '../api';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';

export default function CompareCrawlsPage() {
  const searchString = useSearch();
  const params = useMemo(() => new URLSearchParams(searchString), [searchString]);
  const a = params.get('a') || undefined;
  const b = params.get('b') || undefined;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'compare', { a, b }],
    queryFn: () => crawlerApi.compare({ a, b }),
    staleTime: 60_000,
    retry: false,
  });

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-5">
        <h1 className="text-2xl font-semibold text-brand-text">Compare Crawls</h1>
        <p className="mt-1 text-sm text-brand-text-3">
          Side-by-side diff between two snapshots. Without args, picks
          the two most-recent. Pass <code className="font-mono text-xs">?a=&lt;uuid&gt;&amp;b=&lt;uuid&gt;</code>{' '}
          for explicit selection.
        </p>
      </header>

      {isLoading && (
        <Card><CardContent className="py-4 text-sm text-brand-text-3">Computing diff…</CardContent></Card>
      )}

      {isError && (
        <Card className="border-severity-error">
          <CardContent className="py-4 text-severity-error">
            {error instanceof Error ? error.message : 'Failed to compare snapshots.'}
            <div className="mt-2 text-xs text-brand-text-3">
              Need at least 2 CrawlSnapshot rows. Run{' '}
              <code className="font-mono">python manage.py crawl</code> twice.
            </div>
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          {/* ── Headline ── */}
          <Card className="mb-5 shadow-e2">
            <CardContent className="py-5">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <SnapshotChip label="A" id={data.a_snapshot_id} when={data.a_started_at} engine={data.a_engine} health={data.a_health_score} />
                <SnapshotChip label="B" id={data.b_snapshot_id} when={data.b_started_at} engine={data.b_engine} health={data.b_health_score} />
                <DeltaChip
                  delta={data.health_score_delta}
                  fixed={data.fixed_count}
                  newCount={data.new_count}
                  changed={data.changed_count}
                />
              </div>
            </CardContent>
          </Card>

          {/* ── Per-issue diff ── */}
          <Card className="mb-5">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Per-issue movement</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-brand-border text-left">
                    <tr>
                      <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">Issue</th>
                      <th className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">Severity</th>
                      <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">A</th>
                      <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">B</th>
                      <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Δ</th>
                      <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Fixed</th>
                      <th className="px-2 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">New</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.issues.slice(0, 50).map((iss, i) => (
                      <tr
                        key={iss.slug}
                        className={`border-t border-brand-border ${i % 2 === 1 ? 'bg-brand-surface-2/50' : ''}`}
                      >
                        <td className="px-2 py-2 text-brand-text">{iss.title}</td>
                        <td className="px-2 py-2">
                          <Badge variant={iss.severity === 'error' ? 'error' : iss.severity === 'warning' ? 'warning' : 'notice'}>
                            {iss.severity}
                          </Badge>
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums">{iss.a_count.toLocaleString()}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{iss.b_count.toLocaleString()}</td>
                        <td className={`px-2 py-2 text-right tabular-nums font-semibold ${iss.delta < 0 ? 'text-severity-success' : iss.delta > 0 ? 'text-severity-error' : 'text-brand-text-3'}`}>
                          {iss.delta > 0 ? '+' : ''}{iss.delta}
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-severity-success">{iss.fixed_urls.length}</td>
                        <td className="px-2 py-2 text-right tabular-nums text-severity-error">{iss.new_urls.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data.issues.length > 50 && (
                <div className="mt-2 text-xs text-brand-text-3">
                  Showing 50 biggest movers of {data.issues.length} issues.
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Page-set diffs ── */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <PageDiffCard
              title="Pages added (in B only)"
              tone="notice"
              items={data.pages_added.slice(0, 10).map((p) => ({ url: p.url, hint: `${p.b_status} · ${p.b_word_count.toLocaleString()} words` }))}
              empty="No new URLs."
            />
            <PageDiffCard
              title="Pages removed (in A only)"
              tone="error"
              items={data.pages_removed.slice(0, 10).map((p) => ({ url: p.url, hint: `was ${p.a_status} · ${p.a_word_count.toLocaleString()} words` }))}
              empty="No removed URLs."
            />
            <PageDiffCard
              title="Status changed"
              tone="warning"
              items={data.pages_status_changed.slice(0, 10).map((p) => ({ url: p.url, hint: `${p.a_status} → ${p.b_status}` }))}
              empty="No status changes."
            />
          </div>
        </>
      )}
    </div>
  );
}

function SnapshotChip({
  label,
  id,
  when,
  engine,
  health,
}: {
  label: string;
  id: string;
  when: string;
  engine: string;
  health: number | null;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-brand-text-3">Snapshot {label}</div>
      <div className="mt-1 text-2xl font-semibold text-brand-text">
        {health ?? '—'} <span className="text-xs font-normal text-brand-text-3">score</span>
      </div>
      <div className="mt-1 text-xs text-brand-text-3">
        {engine} · {when ? new Date(when).toLocaleString() : '—'}
      </div>
      <div className="mt-1 break-all font-mono text-xs text-brand-text-4">
        {id.slice(0, 12)}…
      </div>
    </div>
  );
}

function DeltaChip({
  delta,
  fixed,
  newCount,
  changed,
}: {
  delta: number | null;
  fixed: number;
  newCount: number;
  changed: number;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-brand-text-3">Movement</div>
      <div className={`mt-1 text-3xl font-bold leading-none ${delta === null ? 'text-brand-text-3' : delta > 0 ? 'text-severity-success' : delta < 0 ? 'text-severity-error' : 'text-brand-text-3'}`}>
        {delta === null ? '—' : (delta > 0 ? '+' : '') + delta}
        <span className="ml-1 text-sm font-normal text-brand-text-3">pts</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        <Badge variant="success">Fixed {fixed.toLocaleString()}</Badge>
        <Badge variant="error">New {newCount.toLocaleString()}</Badge>
        <Badge variant="warning">Changed {changed.toLocaleString()}</Badge>
      </div>
    </div>
  );
}

function PageDiffCard({
  title,
  tone,
  items,
  empty,
}: {
  title: string;
  tone: 'notice' | 'error' | 'warning';
  items: Array<{ url: string; hint: string }>;
  empty: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-sm">{title}</CardTitle></CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="text-xs text-brand-text-3">{empty}</div>
        ) : (
          <ul className="space-y-1">
            {items.map((it) => (
              <li key={it.url} className="rounded-md bg-brand-surface-2 px-2 py-1.5">
                <a
                  href={it.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate font-mono text-xs text-brand-accent hover:underline"
                  title={it.url}
                >
                  {it.url}
                </a>
                <Badge variant={tone} className="mt-1">{it.hint}</Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
