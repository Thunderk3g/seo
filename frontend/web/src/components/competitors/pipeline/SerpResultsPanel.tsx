// Panel 3: per-engine SERP rows. Tabs by engine. For each query shows
// our rank (if any), featured snippet owner, AI Overview presence,
// and the top-3 organic results so users can see who's beating us.

import { useMemo, useState } from 'react';
import type { GapQuery, GapSerpResultRow } from '../../../api/seoTypes';

export default function SerpResultsPanel({
  results,
  queries,
}: {
  results: GapSerpResultRow[];
  queries: GapQuery[];
}) {
  const byEngine = useMemo(() => {
    const map = new Map<string, GapSerpResultRow[]>();
    results.forEach((r) => {
      const arr = map.get(r.engine) || [];
      arr.push(r);
      map.set(r.engine, arr);
    });
    return map;
  }, [results]);

  const engines = useMemo(() => Array.from(byEngine.keys()).sort(), [byEngine]);
  const [active, setActive] = useState<string | null>(engines[0] ?? null);
  const queryById = useMemo(() => {
    const m = new Map<string, GapQuery>();
    queries.forEach((q) => m.set(q.id, q));
    return m;
  }, [queries]);

  const summary = engines.map((eng) => {
    const rows = byEngine.get(eng) || [];
    const ok = rows.filter((r) => !r.error).length;
    const inTop10 = rows.filter((r) => r.our_position !== null).length;
    const inTop3 = rows.filter(
      (r) => r.our_position !== null && (r.our_position as number) <= 3,
    ).length;
    const featuredOurs = rows.filter(
      (r) => (r.featured_snippet?.domain || '').length > 0,
    ).length;
    return { engine: eng, total: rows.length, ok, inTop10, inTop3, featuredOurs };
  });

  const activeEngine = active && byEngine.has(active) ? active : engines[0];
  const activeRows = activeEngine ? byEngine.get(activeEngine) || [] : [];

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>What the web SERP returned</h2>
        <span className="seo-card-sub">
          {results.length} engine × query cells via SerpAPI
        </span>
      </div>

      {engines.length === 0 ? (
        <div className="seo-empty">
          No SERP data yet. (Stage runs after queries are generated.)
        </div>
      ) : (
        <>
          <div className="gap-pipe-summary-row">
            {summary.map((s) => (
              <div key={s.engine} className="gap-pipe-summary-cell">
                <div className="gap-pipe-summary-label">{s.engine}</div>
                <div className="gap-pipe-summary-value">
                  {s.inTop10}/{s.ok}{' '}
                  <span className="gap-pipe-summary-unit">in top-10</span>
                </div>
                <div className="gap-pipe-summary-sub">
                  {s.inTop3} top-3 · {s.featuredOurs} featured snippets
                </div>
              </div>
            ))}
          </div>

          <div className="gap-pipe-tabs">
            {engines.map((e) => (
              <button
                key={e}
                type="button"
                className={`gap-pipe-tab${
                  e === activeEngine ? ' gap-pipe-tab--active' : ''
                }`}
                onClick={() => setActive(e)}
              >
                {e}
                <span className="gap-pipe-tab-count">
                  {byEngine.get(e)?.length || 0}
                </span>
              </button>
            ))}
          </div>

          <table className="seo-table">
            <thead>
              <tr>
                <th>Query</th>
                <th style={{ width: 80 }}>Our pos</th>
                <th>Featured snippet</th>
                <th>AI Overview</th>
                <th>Top-3 organic</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="seo-empty">
                    No SERP cells for this engine.
                  </td>
                </tr>
              ) : (
                activeRows.map((r) => {
                  const q = queryById.get(r.query_id);
                  const top3 = r.organic.slice(0, 3);
                  const aiHosts =
                    r.ai_overview?.citations
                      ?.slice(0, 3)
                      .map((c) => c.domain || '')
                      .filter(Boolean) || [];
                  return (
                    <tr key={r.id}>
                      <td className="seo-cell-query" title={q?.query}>
                        {q?.query || '(missing)'}
                      </td>
                      <td className="num">
                        {r.our_position == null ? (
                          <span className="gap-pill gap-pill-no">absent</span>
                        ) : r.our_position <= 3 ? (
                          <span className="gap-pill gap-pill-yes">
                            #{r.our_position}
                          </span>
                        ) : (
                          <span className="gap-pill gap-pill-mid">
                            #{r.our_position}
                          </span>
                        )}
                      </td>
                      <td
                        className="seo-cell-query"
                        title={r.featured_snippet?.url || ''}
                        style={{ color: 'var(--text-2)' }}
                      >
                        {r.featured_snippet?.domain || '—'}
                      </td>
                      <td
                        className="seo-cell-query"
                        title={aiHosts.join(', ')}
                        style={{ color: 'var(--text-2)' }}
                      >
                        {aiHosts.length === 0 ? '—' : aiHosts.join(', ')}
                      </td>
                      <td
                        className="seo-cell-query"
                        title={top3.map((o) => o.domain).join(', ')}
                        style={{ color: 'var(--text-2)' }}
                      >
                        {top3.map((o, i) => (
                          <span key={o.url || `${i}`}>
                            {i > 0 && ' › '}
                            {o.domain}
                          </span>
                        ))}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
