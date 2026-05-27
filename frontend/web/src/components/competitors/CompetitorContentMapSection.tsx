/**
 * CompetitorContentMapSection — per-competitor content cluster summary.
 *
 * Each competitor has its own PageEmbedding rows (one per snapshot), so
 * the cluster signal is isolated from Bajaj's content map. This component
 * fetches /api/v1/crawler/content/map/3d?domain=<host> which returns the
 * latest non-empty competitor snapshot's 3D-projected page embeddings
 * with their detected page_type and products.
 *
 * Renders a simple page_type / product breakdown — no 3D R3F dependency,
 * keeps the page light. If you want the full 3D scatter, open
 * /crawler/content-map?snapshot=<id> in a new tab.
 */
import { useQuery } from '@tanstack/react-query';
import { crawlerApi } from '../../crawler/api';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';

interface MapPoint {
  url: string;
  page_type?: string;
  products?: string[];
  confidence?: number;
  x?: number;
  y?: number;
  z?: number;
}

interface MapResponse {
  snapshot_id: string;
  snapshot_kind?: string;
  snapshot_domain?: string;
  snapshot_date?: string;
  total: number;
  points: MapPoint[];
  error?: string;
}

export default function CompetitorContentMapSection({
  domain,
}: {
  domain: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['competitor-content-map', domain],
    queryFn: () =>
      crawlerApi.get<MapResponse>('/content/map/3d', { domain }),
    enabled: Boolean(domain),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  return (
    <section className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Content map · {domain}</CardTitle>
        </CardHeader>
        <CardContent className="pt-2">
          {isLoading && (
            <div className="text-sm text-brand-text-3">
              Loading content map…
            </div>
          )}
          {isError && (
            <div className="text-sm text-brand-text-3">
              No content map yet for {domain}. Run
              {' '}<code className="text-xs">python manage.py refresh_content_map --competitor-domain {domain}</code>
              {' '}to build one — or wait for the next nightly refresh.
            </div>
          )}
          {data && data.total === 0 && (
            <div className="text-sm text-brand-text-3">
              Snapshot exists but has zero embedded pages. The embedder
              hasn't processed this competitor yet.
            </div>
          )}
          {data && data.total > 0 && (
            <Body data={data} domain={domain} />
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function Body({ data, domain }: { data: MapResponse; domain: string }) {
  const pageTypeCounts: Record<string, number> = {};
  const productCounts: Record<string, number> = {};
  for (const p of data.points || []) {
    const pt = p.page_type || 'other';
    pageTypeCounts[pt] = (pageTypeCounts[pt] || 0) + 1;
    for (const prod of p.products || []) {
      productCounts[prod] = (productCounts[prod] || 0) + 1;
    }
  }
  const ptRows = Object.entries(pageTypeCounts)
    .sort((a, b) => b[1] - a[1]);
  const prodRows = Object.entries(productCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12);

  const maxPt = Math.max(...ptRows.map(([, v]) => v), 1);
  const maxProd = Math.max(...prodRows.map(([, v]) => v), 1);

  return (
    <div>
      <div className="mb-3 text-xs text-brand-text-3">
        {data.total} embedded pages · snapshot{' '}
        {data.snapshot_date
          ? new Date(data.snapshot_date).toLocaleDateString()
          : '—'}
        {' '}·{' '}
        <a
          className="underline"
          href={`/crawler/content-map?snapshot=${data.snapshot_id}`}
          target="_blank"
          rel="noreferrer"
        >
          open 3D map ↗
        </a>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-brand-text">
            Page types
          </h3>
          {ptRows.length === 0 ? (
            <div className="text-xs text-brand-text-3">No data.</div>
          ) : (
            <ul className="space-y-1">
              {ptRows.map(([k, v]) => (
                <li
                  key={k}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-brand-text-2">{k}</span>
                  <span className="ml-2 flex items-center gap-2">
                    <span
                      className="h-2 rounded bg-brand-accent"
                      style={{ width: `${(v / maxPt) * 120}px` }}
                    />
                    <span className="w-6 text-right tabular-nums">{v}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold text-brand-text">
            Detected products
          </h3>
          {prodRows.length === 0 ? (
            <div className="text-xs text-brand-text-3">
              No product labels detected. (Classifier seeds may not cover
              this competitor's vocabulary yet.)
            </div>
          ) : (
            <ul className="space-y-1">
              {prodRows.map(([k, v]) => (
                <li
                  key={k}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-brand-text-2">{k}</span>
                  <span className="ml-2 flex items-center gap-2">
                    <span
                      className="h-2 rounded bg-emerald-500"
                      style={{ width: `${(v / maxProd) * 120}px` }}
                    />
                    <span className="w-6 text-right tabular-nums">{v}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
