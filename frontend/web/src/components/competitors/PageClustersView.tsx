/**
 * PageClustersView — per-URL cluster breakdown.
 *
 * Counterpart of the corpus-wide content map (3D scatter of all chunks
 * across all pages of a snapshot), scoped to ONE URL. Shows how this
 * single page's content distributes across the rule-based page_type +
 * product taxonomy: 60% product info, 20% calculator/CTA, 15% FAQ, etc.
 *
 * Renders three panels:
 *   - Page-type bars (stacked horizontal bar with % labels)
 *   - Product bars  (same shape)
 *   - 2D scatter of the page's chunks using their cached UMAP coords.
 *     Colored by page_type so visual clusters pop. Hover reveals the
 *     chunk text. Falls back to a list view when fewer than 4 chunks.
 *
 * No external chart deps — pure SVG and Tailwind. Cheap to ship.
 */
import { useMemo } from 'react';
import { usePageClusters } from '../../api/hooks/useCompetitorDetail';

// Palette for the auto-discovered topic clusters — bright, distinct.
// We support up to 10 clusters per page (KMeans clamp on the backend).
const TOPIC_COLOURS = [
  '#003DA5', // Bajaj navy
  '#10B981', // emerald
  '#8B5CF6', // violet
  '#F59E0B', // amber
  '#EC4899', // pink
  '#14B8A6', // teal
  '#EF4444', // red
  '#0EA5E9', // sky
  '#FDB913', // Bajaj gold
  '#A855F7', // purple
];

function colourForTopic(id: number | null): string {
  if (id === null || id === undefined) return '#9CA3AF';
  return TOPIC_COLOURS[id % TOPIC_COLOURS.length];
}

// Color palette synced with PRODUCT_COLOURS elsewhere so the operator
// sees the same dot colors here as on the corpus content map.
const PAGE_TYPE_COLOURS: Record<string, string> = {
  product_landing: '#003DA5',
  product_detail: '#1E40AF',
  calculator: '#10B981',
  blog_guide: '#8B5CF6',
  faq_qa: '#F59E0B',
  legal: '#64748B',
  navigation: '#94A3B8',
  press_news: '#EC4899',
  career: '#14B8A6',
  contact: '#0EA5E9',
  other: '#9CA3AF',
};

const PRODUCT_COLOURS: Record<string, string> = {
  term: '#003DA5',
  ulip: '#8B5CF6',
  endowment: '#0EA5E9',
  retirement: '#10B981',
  child: '#F59E0B',
  group: '#EC4899',
  wellness: '#14B8A6',
  tax: '#EF4444',
  nri: '#FDB913',
  general_life: '#64748B',
};

function colourForPageType(key: string): string {
  return PAGE_TYPE_COLOURS[key] || PAGE_TYPE_COLOURS.other;
}

function BreakdownBars({
  rows,
  colourMap,
  emptyLabel,
}: {
  rows: { label: string; count: number; pct: number; key: string }[];
  colourMap: Record<string, string>;
  emptyLabel: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="text-xs italic text-brand-text-3">{emptyLabel}</div>
    );
  }
  const max = Math.max(...rows.map((r) => r.pct), 1);
  return (
    <ul className="space-y-1">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-2 text-xs">
          <span className="w-40 truncate text-brand-text-2" title={r.label}>
            {r.label}
          </span>
          <div className="relative h-3 flex-1 overflow-hidden rounded bg-brand-surface-2">
            <span
              className="block h-full rounded"
              style={{
                width: `${(r.pct / max) * 100}%`,
                background: colourMap[r.key] || colourMap.other || '#64748B',
              }}
            />
          </div>
          <span className="w-12 text-right tabular-nums text-brand-text-3">
            {r.pct}%
          </span>
          <span className="w-8 text-right tabular-nums text-brand-text-3">
            {r.count}
          </span>
        </li>
      ))}
    </ul>
  );
}

function ChunkScatter({
  chunks,
}: {
  chunks: Array<{
    chunk_idx: number;
    text: string;
    page_type: string;
    topic_cluster_id: number | null;
    coord_x: number | null;
    coord_y: number | null;
  }>;
}) {
  const projected = useMemo(
    () =>
      chunks.filter(
        (c) => c.coord_x !== null && c.coord_y !== null,
      ),
    [chunks],
  );
  if (projected.length === 0) {
    return (
      <div className="rounded border border-dashed border-brand-border bg-brand-surface-2 p-3 text-xs text-brand-text-3">
        No 2D coords yet. Re-run{' '}
        <code>refresh_content_map</code> for this snapshot to project
        chunks into the shared embedding space.
      </div>
    );
  }
  const xs = projected.map((c) => c.coord_x as number);
  const ys = projected.map((c) => c.coord_y as number);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padX = (maxX - minX) * 0.1 || 1;
  const padY = (maxY - minY) * 0.1 || 1;
  const lx = minX - padX;
  const rx = maxX + padX;
  const ly = minY - padY;
  const ry = maxY + padY;
  const W = 480;
  const H = 240;
  const scaleX = (v: number) => ((v - lx) / (rx - lx)) * W;
  // SVG y axis goes down — flip so larger y is up on screen.
  const scaleY = (v: number) => H - ((v - ly) / (ry - ly)) * H;

  return (
    <div className="overflow-x-auto">
      <svg
        width={W}
        height={H}
        className="block rounded border border-brand-border bg-white"
        role="img"
        aria-label="Page chunk scatter — 2D UMAP projection"
      >
        {/* Axis hint */}
        <text x={6} y={H - 6} fontSize={9} fill="#9CA3AF">
          2D UMAP — chunks of this page in the shared embedding space
        </text>
        {projected.map((c) => (
          <g key={c.chunk_idx}>
            <circle
              cx={scaleX(c.coord_x as number)}
              cy={scaleY(c.coord_y as number)}
              r={5}
              fill={colourForTopic(c.topic_cluster_id)}
              opacity={0.85}
            >
              <title>
                cluster {c.topic_cluster_id ?? '-'} · chunk {c.chunk_idx}
                {'\n'}
                {c.text}
              </title>
            </circle>
          </g>
        ))}
      </svg>
    </div>
  );
}

function ChunkList({
  chunks,
}: {
  chunks: Array<{
    chunk_idx: number;
    text: string;
    page_type: string;
    products: string[];
    confidence: number;
  }>;
}) {
  return (
    <ol className="space-y-2 text-xs">
      {chunks.map((c) => (
        <li
          key={c.chunk_idx}
          className="rounded border border-brand-border bg-white p-2"
        >
          <div className="mb-1 flex items-center gap-2">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: colourForPageType(c.page_type) }}
            />
            <span className="font-semibold text-brand-text">
              {c.page_type || 'other'}
            </span>
            <span className="text-brand-text-3">
              · {c.products.length > 0 ? c.products.join(', ') : 'no product'}
            </span>
            <span className="ml-auto text-brand-text-3">
              chunk #{c.chunk_idx} ·{' '}
              {Math.round((c.confidence || 0) * 100)}%
            </span>
          </div>
          <div className="leading-relaxed text-brand-text-2">
            {c.text || (
              <span className="italic text-brand-text-3">— no text —</span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function PageClustersView({
  snapshotId,
  urlB64,
}: {
  snapshotId: string | null;
  urlB64: string | null;
}) {
  const { data, isLoading, isError, error } = usePageClusters(
    snapshotId,
    urlB64,
  );

  if (isLoading) {
    return (
      <div className="rounded-md border border-brand-border bg-card p-4 text-sm text-brand-text-3">
        Building per-page clusters…
      </div>
    );
  }
  if (isError) {
    const msg = error instanceof Error ? error.message : String(error);
    const is404 = /404/.test(msg);
    return (
      <div className="rounded-md border border-dashed border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
        {is404 ? (
          <>This page has no body text to cluster. Re-crawl the URL first.</>
        ) : (
          msg
        )}
      </div>
    );
  }
  if (!data) return null;

  const ptRows = data.page_type_breakdown.map((r) => ({
    label: r.label,
    count: r.count,
    pct: r.pct,
    key: r.page_type || 'other',
  }));
  const prodRows = data.product_breakdown.map((r) => ({
    label: r.label,
    count: r.count,
    pct: r.pct,
    key: r.product || 'general_life',
  }));

  return (
    <div className="space-y-4">
      {/* Primary view: auto-discovered topics — what this page actually
          covers, derived from semantic clustering of the chunks. The
          rule-based page_type/product breakdowns below are kept as
          secondary reference because they lump the whole page under
          one label ("home", "product_landing", …) which loses signal. */}
      {data.topic_clusters.length > 0 && (
        <div className="rounded-md border border-brand-border bg-card p-4 shadow-e1">
          <div className="mb-3 flex items-baseline justify-between">
            <h3 className="text-sm font-semibold text-brand-text">
              Topics on this page
            </h3>
            <span className="text-xs text-brand-text-3">
              {data.total_chunks} chunk{data.total_chunks === 1 ? '' : 's'}{' '}
              clustered into {data.topic_clusters.length} topic
              {data.topic_clusters.length === 1 ? '' : 's'}
            </span>
          </div>
          <ul className="space-y-2">
            {data.topic_clusters.map((tc) => (
              <li
                key={tc.cluster_id}
                className="rounded border border-brand-border bg-white p-3"
                style={{ borderLeft: `4px solid ${colourForTopic(tc.cluster_id)}` }}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-brand-text">
                      {tc.label}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-brand-text-3">
                      {tc.keywords.slice(0, 6).join(' · ')}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold tabular-nums text-brand-text">
                      {tc.pct}%
                    </div>
                    <div className="text-[10px] uppercase tracking-wide text-brand-text-3">
                      {tc.chunk_count} chunk
                      {tc.chunk_count === 1 ? '' : 's'}
                    </div>
                  </div>
                </div>
                {tc.sample_chunks.length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-brand-text-3 hover:text-brand-text-2">
                      Sample text
                    </summary>
                    <div className="mt-1 space-y-1 rounded bg-brand-surface-2 p-2 text-xs leading-relaxed text-brand-text-2">
                      {tc.sample_chunks.slice(0, 2).map((s) => (
                        <div key={s.chunk_idx}>
                          <span className="font-mono text-[10px] text-brand-text-3">
                            #{s.chunk_idx}
                          </span>{' '}
                          {s.text}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 2D scatter — now colored by topic_cluster_id so the visual
          map matches the topic list above. */}
      {data.chunks.length >= 4 && (
        <div className="rounded-md border border-brand-border bg-card p-4 shadow-e1">
          <div className="mb-2 text-sm font-semibold text-brand-text">
            2D chunk map
          </div>
          <ChunkScatter chunks={data.chunks} />
        </div>
      )}

      {/* Secondary: rule-classifier breakdowns. Lighter visual weight
          because they're often degenerate ("100% home" on a homepage). */}
      <details className="rounded-md border border-brand-border bg-card p-4 shadow-e1">
        <summary className="cursor-pointer text-sm font-semibold text-brand-text">
          Rule-classifier breakdown (page-type + product)
        </summary>
        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              By page-type
            </div>
            <BreakdownBars
              rows={ptRows}
              colourMap={PAGE_TYPE_COLOURS}
              emptyLabel="No page-type classifications yet."
            />
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              By product
            </div>
            <BreakdownBars
              rows={prodRows}
              colourMap={PRODUCT_COLOURS}
              emptyLabel="No product signals on this page's chunks."
            />
          </div>
        </div>
      </details>

      <div className="rounded-md border border-brand-border bg-card p-4 shadow-e1">
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-brand-text">
            Chunk inventory
          </h3>
          <span className="text-xs text-brand-text-3">
            Each chunk is one ~500-char slice of the page's body text.
          </span>
        </div>
        <ChunkList chunks={data.chunks} />
      </div>
    </div>
  );
}
