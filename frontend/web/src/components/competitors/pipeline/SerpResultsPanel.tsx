// Panel 3: per-engine SERP rows. Tabs by engine, with a device toggle
// (desktop / mobile) when the run captured both — Google's rankings
// drift between surfaces and users want to see both sides.

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

  const activeEngine = active && byEngine.has(active) ? active : engines[0];
  const engineRows = activeEngine ? byEngine.get(activeEngine) || [] : [];

  // Devices available for the active engine (mobile-only or desktop-only
  // runs collapse the toggle). Sort so desktop renders first when both
  // are present — matches the operator's mental model.
  const engineDevices = useMemo(() => {
    const set = new Set<string>();
    engineRows.forEach((r) => set.add((r.device || 'desktop').toLowerCase()));
    return Array.from(set).sort((a, b) => {
      if (a === b) return 0;
      if (a === 'desktop') return -1;
      if (b === 'desktop') return 1;
      return a.localeCompare(b);
    });
  }, [engineRows]);

  const [activeDevice, setActiveDevice] = useState<string | null>(null);
  const resolvedDevice =
    activeDevice && engineDevices.includes(activeDevice)
      ? activeDevice
      : engineDevices[0] ?? null;

  const summary = engines.map((eng) => {
    const rows = byEngine.get(eng) || [];
    // Summary numbers use the resolved device (or all rows if the
    // engine has no rows on the resolved device, e.g. mobile-skipped
    // by Bing on a desktop+mobile run).
    const deviceRows = resolvedDevice
      ? rows.filter((r) => (r.device || 'desktop').toLowerCase() === resolvedDevice)
      : rows;
    const scoped = deviceRows.length > 0 ? deviceRows : rows;
    const ok = scoped.filter((r) => !r.error).length;
    const inTop10 = scoped.filter((r) => r.our_position !== null).length;
    const inTop3 = scoped.filter(
      (r) => r.our_position !== null && (r.our_position as number) <= 3,
    ).length;
    const featuredOurs = scoped.filter(
      (r) => (r.featured_snippet?.domain || '').length > 0,
    ).length;
    return { engine: eng, total: scoped.length, ok, inTop10, inTop3, featuredOurs };
  });

  const activeRows = resolvedDevice
    ? engineRows.filter(
        (r) => (r.device || 'desktop').toLowerCase() === resolvedDevice,
      )
    : engineRows;

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>What the web SERP returned</h2>
        <span className="seo-card-sub">
          {results.length} engine × device × query cells via SerpAPI
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

          {engineDevices.length > 1 && (
            <div
              className="gap-pipe-tabs"
              style={{ marginTop: 8, gap: 6 }}
              role="tablist"
              aria-label="Device"
            >
              {engineDevices.map((d) => {
                const count = engineRows.filter(
                  (r) => (r.device || 'desktop').toLowerCase() === d,
                ).length;
                return (
                  <button
                    key={d}
                    type="button"
                    className={`gap-pipe-tab${
                      d === resolvedDevice ? ' gap-pipe-tab--active' : ''
                    }`}
                    onClick={() => setActiveDevice(d)}
                    title={`Show ${d} SERP rows`}
                  >
                    {d}
                    <span className="gap-pipe-tab-count">{count}</span>
                  </button>
                );
              })}
            </div>
          )}

          <table className="seo-table">
            <thead>
              <tr>
                <th>Query</th>
                <th style={{ width: 80 }}>Our pos</th>
                <th>Featured snippet</th>
                <th>AI Overview</th>
                <th>Top organic results</th>
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
                  // Surface every organic result the adapter captured
                  // (up to SERP_API_RESULTS_PER_QUERY, default 25). The
                  // backend already trims at result_per_query so we
                  // don't need a UI-side cap.
                  const organic = r.organic;
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
                        className="serp-organic-cell"
                        title={organic.map((o) => `${o.position}. ${o.domain}`).join('\n')}
                      >
                        {organic.length === 0 ? (
                          <span style={{ color: 'var(--text-2)' }}>—</span>
                        ) : (
                          <span className="serp-organic-list">
                            {organic.map((o, i) => (
                              <a
                                key={o.url || `${i}`}
                                href={o.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="serp-organic-chip"
                                title={`#${o.position} · ${o.title || o.domain}`}
                              >
                                <span className="serp-organic-pos">
                                  {o.position}
                                </span>
                                <span className="serp-organic-domain">
                                  {o.domain}
                                </span>
                              </a>
                            ))}
                          </span>
                        )}
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
