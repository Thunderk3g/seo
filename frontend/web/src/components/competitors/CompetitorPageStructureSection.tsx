/**
 * CompetitorPageStructureSection — LLM-clustered view of a competitor's
 * pages.
 *
 * Hits /api/v1/seo/competitor/<domain>/page-structure/ which groups all
 * of a competitor's CrawlerPageResult rows into 5-10 named topical
 * clusters via the LLM (NOT sentence-transformers — the LLM names each
 * cluster with operator-readable labels like "Term Insurance Products"
 * or "Customer Service / Manage Policy"). Each page in a cluster
 * carries a `source` blob (snapshot id / kind / engine / crawl_mode /
 * started_at) so the operator can see where the data came from — which
 * crawl wrote which row, on what date, via which mode.
 *
 * UI:
 *   - One card per cluster, sized proportionally to chunk %
 *   - Cluster header: name, rationale, page count, %
 *   - Expandable page list with per-page data-source badge:
 *       [scrapy_competitor · sitemap · 2026-05-26]
 *   - Refresh button forces a fresh LLM call (24h cache otherwise)
 */
import { useState } from 'react';
import {
  useCompetitorPageStructure,
  type PageStructureCluster,
  type PageStructureEntry,
} from '../../api/hooks/useCompetitorDetail';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Button } from '../ui/button';

const CLUSTER_COLOURS = [
  '#003DA5', '#10B981', '#8B5CF6', '#F59E0B',
  '#EC4899', '#14B8A6', '#EF4444', '#0EA5E9',
  '#FDB913', '#A855F7', '#64748B',
];

function colourForCluster(id: number): string {
  return CLUSTER_COLOURS[id % CLUSTER_COLOURS.length];
}

export default function CompetitorPageStructureSection({
  domain,
}: {
  domain: string;
}) {
  const [force, setForce] = useState(false);
  const { data, isLoading, isError, error, refetch, isFetching } =
    useCompetitorPageStructure(domain, { force });

  return (
    <section className="mt-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base">
            Page structure · {domain}
          </CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <span className="text-[10px] text-brand-text-3">
                {data.cached ? 'cached' : 'live'} · {data.total_pages_sampled}/
                {data.total_pages_in_corpus} pages · {data.model_used} · $
                {data.cost_usd.toFixed(4)}
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={isFetching}
              onClick={() => {
                setForce(true);
                refetch();
              }}
            >
              {isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          {isLoading && (
            <div className="text-sm text-brand-text-3">
              Asking the LLM to cluster {domain}'s pages…
            </div>
          )}
          {isError && (
            <div className="text-sm text-brand-text-3">
              Failed to build page structure:{' '}
              {error instanceof Error ? error.message : 'unknown error'}
            </div>
          )}
          {data && data.error && (
            <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {data.error}
            </div>
          )}
          {data && data.clusters && data.clusters.length > 0 && (
            <Clusters
              clusters={data.clusters}
              totalSampled={data.total_pages_sampled}
            />
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function Clusters({
  clusters,
  totalSampled,
}: {
  clusters: PageStructureCluster[];
  totalSampled: number;
}) {
  return (
    <div className="space-y-3">
      <div className="text-xs text-brand-text-3">
        {clusters.length} topical clusters across {totalSampled} pages.
        Each cluster is named by the LLM based on the URL + title patterns
        of the pages it contains. Click a cluster to see its pages and
        their data-source provenance.
      </div>
      <div className="space-y-2">
        {clusters.map((c) => (
          <ClusterCard
            key={c.cluster_id}
            cluster={c}
            totalSampled={totalSampled}
          />
        ))}
      </div>
    </div>
  );
}

function ClusterCard({
  cluster,
  totalSampled,
}: {
  cluster: PageStructureCluster;
  totalSampled: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const pct = totalSampled
    ? Math.round((cluster.pages.length / totalSampled) * 100)
    : 0;
  const colour = colourForCluster(cluster.cluster_id);
  return (
    <div
      className="overflow-hidden rounded border border-brand-border bg-white"
      style={{ borderLeft: `4px solid ${colour}` }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left"
      >
        <span className="w-3 text-xs text-brand-text-3">
          {expanded ? '▾' : '▸'}
        </span>
        <span className="text-sm font-semibold text-brand-text">
          {cluster.name}
        </span>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-white"
          style={{ background: colour }}
        >
          {cluster.pages.length}
        </span>
        <span className="text-xs text-brand-text-3">{pct}%</span>
        {cluster.rationale && (
          <span className="ml-2 truncate text-xs italic text-brand-text-3">
            — {cluster.rationale}
          </span>
        )}
      </button>
      {expanded && (
        <div className="border-t border-brand-border bg-brand-surface-2">
          <ul className="divide-y divide-brand-border">
            {cluster.pages.map((p) => (
              <PageRow key={p.url} entry={p} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function PageRow({ entry }: { entry: PageStructureEntry }) {
  const src = entry.source;
  const sourceLabel = [
    src.snapshot_engine || '?',
    src.crawl_mode || null,
    src.snapshot_started_at ? src.snapshot_started_at.slice(0, 10) : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <li className="px-3 py-2 text-xs">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <a
            href={entry.url}
            target="_blank"
            rel="noreferrer"
            className="block font-medium text-brand-text hover:text-brand-accent hover:underline"
            title={entry.url}
          >
            {entry.title || '(untitled)'}
          </a>
          <div className="break-all font-mono text-[10px] text-brand-text-3">
            {entry.url}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="rounded bg-brand-surface px-1.5 py-0.5 text-[9px] font-semibold uppercase text-brand-text-3">
            {sourceLabel}
          </span>
          <span className="tabular-nums text-[10px] text-brand-text-3">
            {entry.word_count.toLocaleString()} words
          </span>
        </div>
      </div>
    </li>
  );
}
