/**
 * InternalLinkingPanel — internal link equity over the latest crawl.
 *
 * Reads /api/v1/crawler/pagerank (services/pagerank.py). "in_degree" is the
 * number of internal pages linking TO a URL — i.e. top pages by internal
 * linking. Also surfaces orphan count (zero inbound internal links) and the
 * total node/edge counts of the internal link graph.
 */
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { crawlerApi } from '../api';

function shortUrl(u: string): string {
  try {
    const { pathname } = new URL(u);
    return pathname === '/' ? '/ (home)' : pathname;
  } catch {
    return u;
  }
}

export default function InternalLinkingPanel() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'pagerank'],
    queryFn: () => crawlerApi.pagerank(),
    staleTime: 60_000,
  });

  return (
    <div className="bajaj-ui">
      <Card className="mb-4 shadow-e2">
        <CardHeader className="pb-3">
          <CardTitle>
            Internal Linking
            <span className="ml-2 text-xs font-normal text-brand-text-4">
              top pages by inbound internal links
            </span>
          </CardTitle>
        </CardHeader>

        <CardContent>
          {isLoading && <div className="text-sm text-brand-text-3">Computing link graph…</div>}

          {isError && (
            <div className="text-sm text-severity-error">
              Internal linking unavailable: {error instanceof Error ? error.message : 'unknown error'}
            </div>
          )}

          {data && !data.summary.computed && (
            <div className="text-sm text-brand-text-3">
              No internal link graph yet — run a crawl to populate it.
            </div>
          )}

          {data && data.summary.computed && (
            <>
              <div className="mb-4 flex flex-wrap gap-6">
                <Stat label="Pages in graph" value={data.summary.node_count} />
                <Stat label="Internal links" value={data.summary.edge_count} />
                <Stat
                  label="Orphans (0 inbound)"
                  value={data.summary.orphan_count}
                  tone={data.summary.orphan_count > 0 ? 'warn' : 'ok'}
                />
              </div>

              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Most-linked pages
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-brand-text-4">
                    <th className="pb-1 font-medium">Page</th>
                    <th className="pb-1 text-right font-medium">Inbound</th>
                    <th className="pb-1 text-right font-medium">Outbound</th>
                    <th className="pb-1 text-right font-medium">Link score</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top.slice(0, 12).map((p) => (
                    <tr key={p.url} className="border-t border-brand-border">
                      <td className="py-1.5 pr-2">
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-mono text-brand-text hover:underline"
                          title={p.url}
                        >
                          {shortUrl(p.url)}
                        </a>
                      </td>
                      <td className="py-1.5 text-right font-semibold text-brand-text">
                        {p.in_degree.toLocaleString()}
                      </td>
                      <td className="py-1.5 text-right text-brand-text-3">
                        {p.out_degree.toLocaleString()}
                      </td>
                      <td className="py-1.5 text-right text-brand-text-3">
                        {Math.round(p.pagerank_score)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'ok' | 'warn';
}) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold leading-none text-brand-text">
          {value.toLocaleString()}
        </span>
        {tone === 'warn' && value > 0 && <Badge variant="warning">fix</Badge>}
      </div>
      <div className="mt-1 text-xs text-brand-text-3">{label}</div>
    </div>
  );
}
