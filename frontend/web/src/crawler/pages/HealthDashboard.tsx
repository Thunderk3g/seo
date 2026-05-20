/**
 * HealthDashboard — `/health` route.
 *
 * Ahrefs-style overview built on Phase 1's Health Score data +
 * Phase 4's PageRank and near-duplicate services. Shows in one
 * scroll:
 *
 *   1. Top KPI strip — score + tier + severity counts + trend arrow
 *      (trend coming in Phase 5 — for now shows only "today's" score)
 *   2. Category tiles — 8 audit categories with issue-type counts
 *   3. Top errors panel — most-affecting issue types (deep link to
 *      drill-in)
 *   4. Top-linked pages — PageRank top-10
 *   5. Near-duplicate clusters — biggest clusters with sample URLs
 *
 * Bajaj brand via shadcn primitives scoped under .bajaj-ui.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'wouter';
import { crawlerApi } from '../api';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';

type Tier = 'Excellent' | 'Good' | 'Fair' | 'Weak';

const TIER_TONE: Record<Tier, 'success' | 'notice' | 'warning' | 'error'> = {
  Excellent: 'success',
  Good: 'notice',
  Fair: 'warning',
  Weak: 'error',
};

const TIER_TEXT_CLASS: Record<Tier, string> = {
  Excellent: 'text-severity-success',
  Good: 'text-severity-notice',
  Fair: 'text-severity-warning',
  Weak: 'text-severity-error',
};

const CATEGORY_LABEL: Record<string, string> = {
  crawlability: 'Crawlability',
  indexability: 'Indexability',
  content: 'Content',
  titles: 'Titles',
  performance: 'Performance',
  cwv: 'Core Web Vitals',
  urls: 'URLs',
  compliance: 'Compliance',
};

export default function HealthDashboard() {
  const health = useQuery({
    queryKey: ['crawler', 'health-score'],
    queryFn: () => crawlerApi.healthScore(),
    staleTime: 60_000,
  });

  const pageRank = useQuery({
    queryKey: ['crawler', 'pagerank'],
    queryFn: () => crawlerApi.pagerank(),
    staleTime: 5 * 60_000,
  });

  const dups = useQuery({
    queryKey: ['crawler', 'near-duplicates'],
    queryFn: () => crawlerApi.nearDuplicates({ n: 10 }),
    staleTime: 5 * 60_000,
  });

  const tier = (health.data?.tier || 'Weak') as Tier;
  const tierTone = TIER_TONE[tier];
  const tierTextClass = TIER_TEXT_CLASS[tier];

  const categoryEntries = useMemo(() => {
    const cc = health.data?.category_counts || {};
    return Object.entries(cc).sort(([, a], [, b]) => b - a);
  }, [health.data?.category_counts]);

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-brand-text">Health Dashboard</h1>
          <p className="mt-1 text-sm text-brand-text-3">
            Ahrefs-style overview of crawl health. Health Score,
            category coverage, internal link equity, near-duplicate
            clusters — all in one view.
          </p>
        </div>
        <Link href="/crawler/issues">
          <Button variant="outline" size="sm">
            Open Issues triage
          </Button>
        </Link>
      </header>

      {/* ── TOP KPI strip ── */}
      <Card className="mb-5 shadow-e2">
        <CardContent className="py-6">
          {health.isLoading ? (
            <div className="text-sm text-brand-text-3">Loading…</div>
          ) : health.data ? (
            <div className="flex flex-wrap items-baseline gap-8">
              <div>
                <div className={`text-6xl font-bold leading-none ${tierTextClass}`}>
                  {health.data.score}
                  <span className="ml-1 text-2xl text-brand-text-3">/ 100</span>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant={tierTone}>{tier}</Badge>
                  <span className="text-xs text-brand-text-3">
                    {health.data.urls_without_error.toLocaleString()} of{' '}
                    {health.data.total_urls.toLocaleString()} URLs without errors
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-6">
                <KpiStat
                  label="Errors"
                  count={health.data.severity_counts.error}
                  types={health.data.issue_type_counts.error}
                  tone="error"
                />
                <KpiStat
                  label="Warnings"
                  count={health.data.severity_counts.warning}
                  types={health.data.issue_type_counts.warning}
                  tone="warning"
                />
                <KpiStat
                  label="Notices"
                  count={health.data.severity_counts.notice}
                  types={health.data.issue_type_counts.notice}
                  tone="notice"
                />
              </div>
            </div>
          ) : (
            <div className="text-severity-error">Failed to compute Health Score.</div>
          )}
        </CardContent>
      </Card>

      {/* ── Category tiles ── */}
      {categoryEntries.length > 0 && (
        <section className="mb-5">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-brand-text-3">
            Issue types per category
          </h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {categoryEntries.map(([cat, n]) => (
              <Card key={cat}>
                <CardContent className="py-4">
                  <div className="text-xs uppercase tracking-wide text-brand-text-3">
                    {CATEGORY_LABEL[cat] || cat}
                  </div>
                  <div className="mt-1 text-2xl font-semibold text-brand-text">
                    {n}
                  </div>
                  <div className="text-xs text-brand-text-3">
                    distinct issue {n === 1 ? 'type' : 'types'}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* ── Top errors panel ── */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Top errors by affected URLs</CardTitle>
          </CardHeader>
          <CardContent>
            {health.data && health.data.top_errors.length > 0 ? (
              <ul className="space-y-1.5">
                {health.data.top_errors.map((e) => (
                  <li
                    key={e.slug}
                    className="flex items-center justify-between rounded-md bg-brand-surface-2 px-3 py-2 text-sm"
                  >
                    <Link href={`/crawler/issues/${e.slug}`}>
                      <span className="cursor-pointer text-brand-text hover:underline">
                        {e.title}
                      </span>
                    </Link>
                    <Badge variant="error">{e.count.toLocaleString()}</Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-brand-text-3">
                No error-severity issues firing.
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Top-linked pages (PageRank) ── */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">
              Top-linked pages
              <span className="ml-2 text-xs font-normal text-brand-text-3">
                Internal PageRank
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {pageRank.isLoading ? (
              <div className="text-sm text-brand-text-3">Computing PageRank…</div>
            ) : pageRank.data && pageRank.data.top.length > 0 ? (
              <ul className="space-y-1.5">
                {pageRank.data.top.slice(0, 10).map((p) => (
                  <li
                    key={p.url}
                    className="flex items-center justify-between gap-3 rounded-md bg-brand-surface-2 px-3 py-2 text-sm"
                  >
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noreferrer"
                      className="truncate font-mono text-xs text-brand-text hover:underline"
                      title={p.url}
                    >
                      {p.url}
                    </a>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="text-xs text-brand-text-3">
                        in {p.in_degree.toLocaleString()}
                      </span>
                      <Badge variant="notice">{p.pagerank_score}</Badge>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-brand-text-3">
                No PageRank data — run a crawl first.
              </div>
            )}
            {pageRank.data?.summary?.computed && (
              <div className="mt-3 text-xs text-brand-text-3">
                {pageRank.data.summary.node_count.toLocaleString()} nodes ·{' '}
                {pageRank.data.summary.edge_count.toLocaleString()} edges ·{' '}
                {pageRank.data.summary.orphan_count.toLocaleString()} orphans
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Near-duplicate clusters ── */}
      <Card className="mt-5">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Near-duplicate clusters
            <span className="ml-2 text-xs font-normal text-brand-text-3">
              MinHash + LSH at 90% threshold
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {dups.isLoading ? (
            <div className="text-sm text-brand-text-3">Computing clusters…</div>
          ) : dups.data && dups.data.clusters.length > 0 ? (
            <div className="space-y-3">
              <div className="text-xs text-brand-text-3">
                {dups.data.summary.cluster_count.toLocaleString()} clusters cover{' '}
                {dups.data.summary.total_dupes.toLocaleString()} URLs · largest cluster:{' '}
                {dups.data.summary.largest_cluster_size} URLs
              </div>
              <ul className="space-y-2">
                {dups.data.clusters.slice(0, 5).map((c) => (
                  <li
                    key={c.cluster_id}
                    className="rounded-md border border-brand-border bg-brand-surface-2 px-3 py-2"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-medium text-brand-text">
                        {c.representative_title || (
                          <span className="italic text-brand-text-3">— no title —</span>
                        )}
                      </span>
                      <Badge variant="warning">{c.cluster_size} URLs</Badge>
                    </div>
                    <ul className="mt-1 ml-2 space-y-0.5 text-xs text-brand-text-3">
                      {c.member_urls.slice(0, 3).map((u) => (
                        <li key={u} className="truncate font-mono" title={u}>
                          · {u}
                        </li>
                      ))}
                      {c.more_members > 0 && (
                        <li className="text-brand-text-4">
                          · …+{c.more_members} more
                        </li>
                      )}
                    </ul>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="text-sm text-brand-text-3">
              No near-duplicate clusters detected.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function KpiStat({
  label,
  count,
  types,
  tone,
}: {
  label: string;
  count: number;
  types: number;
  tone: 'error' | 'warning' | 'notice';
}) {
  const textClass =
    tone === 'error'
      ? 'text-severity-error'
      : tone === 'warning'
        ? 'text-severity-warning'
        : 'text-severity-notice';
  return (
    <div>
      <div className={`text-3xl font-semibold leading-none ${textClass}`}>
        {count.toLocaleString()}
      </div>
      <div className="mt-1 text-xs text-brand-text-3">
        {label}{' '}
        <span className="text-brand-text-4">
          ({types} {types === 1 ? 'type' : 'types'})
        </span>
      </div>
    </div>
  );
}
