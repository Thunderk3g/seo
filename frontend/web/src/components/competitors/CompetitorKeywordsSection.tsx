/**
 * CompetitorKeywordsSection — what this competitor targets, two views.
 *
 *   Ranking tab → Semrush domain_organic (authoritative, cached). Shows
 *     the keywords they actually rank for, with position + search
 *     volume + estimated traffic share.
 *   Content tab → in-house TF-IDF over the crawled CrawlerPageResult
 *     rows (every subdomain rolled up under the parent brand). Shows
 *     what they *write about* — useful for spotting topics that don't
 *     yet rank but are part of their content strategy.
 *
 * Renders compactly so it slots into the existing CompetitorDetailPage
 * stack without dominating the screen. Each tab gracefully handles
 * "unavailable" responses (e.g. Semrush quota dry) with an inline tile.
 */
import { useState } from 'react';
import {
  useCompetitorKeywordsContent,
  useCompetitorKeywordsSemrush,
} from '../../api/hooks/useCompetitorDetail';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';

type Tab = 'ranking' | 'content';

export default function CompetitorKeywordsSection({
  domain,
}: {
  domain: string;
}) {
  const [tab, setTab] = useState<Tab>('ranking');
  const semrushQ = useCompetitorKeywordsSemrush(domain);
  const contentQ = useCompetitorKeywordsContent(domain);

  return (
    <section className="mt-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base">Keywords · {domain}</CardTitle>
          <div className="inline-flex overflow-hidden rounded border border-brand-border-2">
            <button
              type="button"
              onClick={() => setTab('ranking')}
              className={`px-2 py-1 text-xs font-semibold ${
                tab === 'ranking'
                  ? 'bg-brand-blue text-white'
                  : 'bg-white text-brand-text-2'
              }`}
            >
              Ranking{' '}
              {semrushQ.data?.available && (
                <span className="ml-1 text-[10px] opacity-70">
                  {semrushQ.data.count}
                </span>
              )}
            </button>
            <button
              type="button"
              onClick={() => setTab('content')}
              className={`border-l border-brand-border-2 px-2 py-1 text-xs font-semibold ${
                tab === 'content'
                  ? 'bg-brand-blue text-white'
                  : 'bg-white text-brand-text-2'
              }`}
            >
              Content{' '}
              {contentQ.data?.available && (
                <span className="ml-1 text-[10px] opacity-70">
                  {contentQ.data.count}
                </span>
              )}
            </button>
          </div>
        </CardHeader>
        <CardContent className="pt-2">
          {tab === 'ranking' ? (
            <RankingTab q={semrushQ} />
          ) : (
            <ContentTab q={contentQ} />
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function RankingTab({
  q,
}: {
  q: ReturnType<typeof useCompetitorKeywordsSemrush>;
}) {
  if (q.isLoading) {
    return (
      <div className="text-sm text-brand-text-3">Loading Semrush rankings…</div>
    );
  }
  if (q.isError) {
    return (
      <div className="text-sm text-brand-text-3">
        Failed to load Semrush rankings:{' '}
        {q.error instanceof Error ? q.error.message : 'unknown error'}
      </div>
    );
  }
  const data = q.data;
  if (!data || !data.available) {
    return (
      <div className="rounded border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        Semrush ranking data unavailable.{' '}
        {data?.error && <span className="text-amber-700">({data.error})</span>}
      </div>
    );
  }
  if (data.keywords.length === 0) {
    return (
      <div className="text-sm text-brand-text-3">
        No organic keywords returned for {data.domain}.
      </div>
    );
  }
  return (
    <div className="max-h-[480px] overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-brand-surface text-left text-brand-text-3">
          <tr>
            <th className="px-2 py-1">Keyword</th>
            <th className="px-2 py-1 text-right">Pos</th>
            <th className="px-2 py-1 text-right">Volume</th>
            <th className="px-2 py-1 text-right">Traffic%</th>
            <th className="px-2 py-1 text-right">CPC</th>
            <th className="px-2 py-1">Top URL</th>
          </tr>
        </thead>
        <tbody>
          {data.keywords.map((k, idx) => {
            const delta = k.previous_position
              ? k.previous_position - k.position
              : 0;
            return (
              <tr key={`${idx}-${k.keyword}-${k.url}`} className="border-t border-brand-border">
                <td className="px-2 py-1 align-top font-medium text-brand-text">
                  {k.keyword}
                </td>
                <td className="px-2 py-1 align-top text-right tabular-nums">
                  {k.position}
                  {delta !== 0 && (
                    <span
                      className={
                        delta > 0
                          ? 'ml-1 text-[10px] text-green-700'
                          : 'ml-1 text-[10px] text-red-700'
                      }
                    >
                      {delta > 0 ? `↑${delta}` : `↓${-delta}`}
                    </span>
                  )}
                </td>
                <td className="px-2 py-1 align-top text-right tabular-nums">
                  {k.search_volume.toLocaleString()}
                </td>
                <td className="px-2 py-1 align-top text-right tabular-nums">
                  {k.traffic_pct.toFixed(2)}%
                </td>
                <td className="px-2 py-1 align-top text-right tabular-nums text-brand-text-3">
                  ${k.cpc.toFixed(2)}
                </td>
                <td className="px-2 py-1 align-top">
                  {k.url ? (
                    <a
                      href={k.url}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all font-mono text-brand-accent hover:underline"
                    >
                      {k.url.length > 60 ? `${k.url.slice(0, 60)}…` : k.url}
                    </a>
                  ) : (
                    <span className="text-brand-text-3">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ContentTab({
  q,
}: {
  q: ReturnType<typeof useCompetitorKeywordsContent>;
}) {
  if (q.isLoading) {
    return (
      <div className="text-sm text-brand-text-3">
        Running TF-IDF over crawled content…
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="text-sm text-brand-text-3">
        Failed to compute content keywords:{' '}
        {q.error instanceof Error ? q.error.message : 'unknown error'}
      </div>
    );
  }
  const data = q.data;
  if (!data || !data.available) {
    return (
      <div className="rounded border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        Content keywords unavailable.{' '}
        {data?.error && <span className="text-amber-700">({data.error})</span>}
      </div>
    );
  }
  if (data.keywords.length === 0) {
    return (
      <div className="text-sm text-brand-text-3">
        No discriminating keywords surfaced for {data.domain}.
      </div>
    );
  }
  const maxScore = Math.max(...data.keywords.map((k) => k.score), 1);
  return (
    <div>
      <div className="mb-2 text-xs text-brand-text-3">
        {data.page_count?.toLocaleString()} pages across{' '}
        {data.subdomain_count} subdomain
        {data.subdomain_count === 1 ? '' : 's'}, parent ={' '}
        <span className="font-medium">{data.parent_domain}</span>
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {data.keywords.slice(0, 30).map((k) => {
          const w = 0.7 + 0.9 * (k.score / maxScore);
          return (
            <span
              key={k.keyword}
              title={`score ${k.score.toFixed(3)} · ${k.page_count} pages`}
              className="rounded bg-brand-surface-2 px-2 py-0.5 text-brand-text"
              style={{ fontSize: `${(w * 12).toFixed(1)}px`, lineHeight: 1.5 }}
            >
              {k.keyword}
            </span>
          );
        })}
      </div>
      <div className="max-h-[360px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-brand-surface text-left text-brand-text-3">
            <tr>
              <th className="px-2 py-1">Keyword</th>
              <th className="px-2 py-1 text-right">Score</th>
              <th className="px-2 py-1 text-right">Pages</th>
              <th className="px-2 py-1">Sample URLs</th>
            </tr>
          </thead>
          <tbody>
            {data.keywords.map((k) => (
              <tr key={k.keyword} className="border-t border-brand-border">
                <td className="px-2 py-1 align-top font-medium text-brand-text">
                  {k.keyword}
                </td>
                <td className="px-2 py-1 align-top text-right tabular-nums">
                  {k.score.toFixed(2)}
                </td>
                <td className="px-2 py-1 align-top text-right tabular-nums">
                  {k.page_count}
                </td>
                <td className="px-2 py-1 align-top">
                  {k.sample_pages.length === 0 ? (
                    <span className="text-brand-text-3">—</span>
                  ) : (
                    <ul className="space-y-0.5">
                      {k.sample_pages.map((p) => (
                        <li key={p.url} className="truncate">
                          <a
                            href={p.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-brand-accent hover:underline"
                            title={p.url}
                          >
                            {p.title || p.url}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
