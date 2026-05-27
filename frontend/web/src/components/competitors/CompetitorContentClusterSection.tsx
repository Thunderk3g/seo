/**
 * CompetitorContentClusterSection — per-competitor content cluster tree.
 *
 * Counterpart to CompetitorContentMapSection. The MAP section needs
 * PageEmbedding rows (refresh_content_map must have run for that competitor
 * domain); the CLUSTER tree only needs CrawlerPageResult rows, which exist
 * from any crawl. So this section renders even when the competitor's
 * embeddings haven't been built yet — operator gets immediate signal
 * instead of the "Run refresh_content_map" placeholder.
 *
 * Hits /api/v1/crawler/content/clusters?domain=<host> which resolves to
 * the latest non-empty competitor snapshot for that domain on the backend.
 *
 * Renders two views:
 *   • Diagram — re-uses ContentDendrogram (same SVG tree as ours-side page)
 *   • Text    — collapsible Product → Page-type → URL list
 *
 * No 3D dependency, keeps the competitor detail page light.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { crawlerApi } from '../../crawler/api';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import ContentDendrogram from '../../crawler/components/ContentDendrogram';

const PRODUCT_COLOURS: Record<string, string> = {
  term:         '#003DA5',
  ulip:         '#8B5CF6',
  endowment:    '#0EA5E9',
  retirement:   '#10B981',
  child:        '#F59E0B',
  group:        '#EC4899',
  wellness:     '#14B8A6',
  tax:          '#EF4444',
  nri:          '#FDB913',
  general_life: '#64748B',
};

type View = 'diagram' | 'text';

export default function CompetitorContentClusterSection({
  domain,
}: {
  domain: string;
}) {
  const [view, setView] = useState<View>('diagram');
  const [openProducts, setOpenProducts] = useState<Set<string>>(new Set());
  const [openPageTypes, setOpenPageTypes] = useState<Set<string>>(new Set());

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['competitor-content-clusters', domain],
    queryFn: () => crawlerApi.contentClusters({ domain, mode: 'primary' }),
    enabled: Boolean(domain),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const toggleProduct = (k: string) =>
    setOpenProducts((prev) => {
      const n = new Set(prev);
      n.has(k) ? n.delete(k) : n.add(k);
      return n;
    });
  const togglePageType = (k: string) =>
    setOpenPageTypes((prev) => {
      const n = new Set(prev);
      n.has(k) ? n.delete(k) : n.add(k);
      return n;
    });

  return (
    <section className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Content clusters · {domain}</CardTitle>
        </CardHeader>
        <CardContent className="pt-2">
          {isLoading && (
            <div className="text-sm text-brand-text-3">
              Loading clusters…
            </div>
          )}
          {isError && (
            <div className="text-sm text-brand-text-3">
              No crawled snapshot yet for {domain}.{' '}
              {(error as Error)?.message ? (
                <span className="text-xs text-brand-text-3">
                  ({(error as Error).message})
                </span>
              ) : null}
            </div>
          )}
          {data && data.totals.classified === 0 && (
            <div className="text-sm text-brand-text-3">
              Snapshot exists ({data.totals.pages} pages) but Tier-1 rules
              didn't classify any into known products. Likely a vocabulary
              gap — every page landed in "Uncertain".
            </div>
          )}
          {data && data.totals.classified > 0 && (
            <>
              <div className="mb-3 flex items-center gap-3 text-xs text-brand-text-3">
                <span>
                  {data.totals.pages.toLocaleString()} pages ·{' '}
                  {data.totals.classified.toLocaleString()} classified ·{' '}
                  {data.totals.uncertain.toLocaleString()} uncertain · snapshot{' '}
                  {data.snapshot_date
                    ? new Date(data.snapshot_date).toLocaleDateString()
                    : '—'}
                </span>
                <span className="flex-1" />
                <div className="inline-flex overflow-hidden rounded border border-brand-border-2">
                  <button
                    type="button"
                    onClick={() => setView('diagram')}
                    className={`px-2 py-1 text-xs font-semibold ${
                      view === 'diagram'
                        ? 'bg-brand-blue text-white'
                        : 'bg-white text-brand-text-2'
                    }`}
                  >
                    Diagram
                  </button>
                  <button
                    type="button"
                    onClick={() => setView('text')}
                    className={`px-2 py-1 text-xs font-semibold border-l border-brand-border-2 ${
                      view === 'text'
                        ? 'bg-brand-blue text-white'
                        : 'bg-white text-brand-text-2'
                    }`}
                  >
                    Text
                  </button>
                </div>
              </div>

              {view === 'diagram' && (
                <ContentDendrogram
                  products={data.products}
                  rootLabel={`${domain} · ${data.totals.classified} pages`}
                />
              )}

              {view === 'text' && (
                <TextTree
                  data={data}
                  openProducts={openProducts}
                  openPageTypes={openPageTypes}
                  toggleProduct={toggleProduct}
                  togglePageType={togglePageType}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

type ClusterData = Awaited<ReturnType<typeof crawlerApi.contentClusters>>;

function TextTree({
  data,
  openProducts,
  openPageTypes,
  toggleProduct,
  togglePageType,
}: {
  data: ClusterData;
  openProducts: Set<string>;
  openPageTypes: Set<string>;
  toggleProduct: (k: string) => void;
  togglePageType: (k: string) => void;
}) {
  return (
    <div className="space-y-1">
      {data.products.map((prod) => {
        const colour = PRODUCT_COLOURS[prod.product] || '#64748B';
        const isOpen = openProducts.has(prod.product);
        return (
          <div
            key={prod.product}
            className="overflow-hidden rounded border border-brand-border-2 bg-white"
          >
            <button
              type="button"
              onClick={() => toggleProduct(prod.product)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left"
              style={{ borderLeft: `4px solid ${colour}` }}
            >
              <span className="w-3 text-xs text-brand-text-3">
                {isOpen ? '▾' : '▸'}
              </span>
              <span className="text-sm font-semibold text-brand-text">
                {prod.label}
              </span>
              <span
                className="rounded-full px-2 py-0.5 text-xs font-semibold text-white"
                style={{ background: colour }}
              >
                {prod.count}
              </span>
              <span className="text-xs text-brand-text-3">
                across {prod.page_types.length} page type
                {prod.page_types.length === 1 ? '' : 's'}
              </span>
            </button>
            {isOpen && (
              <div className="border-t border-brand-border-2 bg-brand-bg-2">
                {prod.page_types.map((pt) => {
                  const key = `${prod.product}:${pt.page_type}`;
                  const ptOpen = openPageTypes.has(key);
                  return (
                    <div
                      key={key}
                      className="border-b border-brand-border-2 last:border-b-0"
                    >
                      <button
                        type="button"
                        onClick={() => togglePageType(key)}
                        className="flex w-full items-center gap-2 py-1.5 pl-8 pr-3 text-left"
                      >
                        <span className="w-3 text-xs text-brand-text-3">
                          {ptOpen ? '▾' : '▸'}
                        </span>
                        <span className="text-sm text-brand-text-2">
                          {pt.label}
                        </span>
                        <span className="rounded-full bg-brand-border-2 px-2 py-0.5 text-[10px] font-semibold text-brand-text-2">
                          {pt.count}
                        </span>
                      </button>
                      {ptOpen && (
                        <ul className="space-y-1 px-3 pb-2 pl-12">
                          {pt.pages.map((page) => (
                            <li
                              key={page.url}
                              className="flex items-center gap-2 text-xs"
                            >
                              <a
                                href={page.url}
                                target="_blank"
                                rel="noreferrer"
                                className="min-w-0 flex-1 truncate text-brand-blue hover:underline"
                                title={page.url}
                              >
                                <span className="font-medium">
                                  {page.title || '(untitled)'}
                                </span>
                                <span className="ml-2 text-brand-text-3">
                                  {page.url}
                                </span>
                              </a>
                              <span
                                className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                                style={confStyle(page.confidence)}
                              >
                                {Math.round(page.confidence * 100)}%
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {data.uncertain.count > 0 && (
        <details className="mt-3 overflow-hidden rounded border border-amber-300 bg-amber-50">
          <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-amber-800">
            Uncertain · {data.uncertain.count}
            <span className="ml-2 text-xs font-normal text-amber-700">
              Tier-1 rules couldn't pin these down
            </span>
          </summary>
          <ul className="space-y-1 px-3 pb-3 pl-6 pt-1">
            {data.uncertain.pages.slice(0, 100).map((page) => (
              <li key={page.url} className="text-xs">
                <a
                  href={page.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-amber-900 hover:underline"
                  title={page.url}
                >
                  {page.title || page.url}
                </a>
              </li>
            ))}
            {data.uncertain.pages.length > 100 && (
              <li className="text-xs text-amber-700">
                + {data.uncertain.pages.length - 100} more
              </li>
            )}
          </ul>
        </details>
      )}
    </div>
  );
}

function confStyle(value: number): React.CSSProperties {
  if (value >= 0.85) return { background: '#DCFCE7', color: '#166534' };
  if (value >= 0.70) return { background: '#FEF9C3', color: '#854D0E' };
  if (value >= 0.60) return { background: '#FFEDD5', color: '#9A3412' };
  return { background: '#E5E7EB', color: '#374151' };
}

