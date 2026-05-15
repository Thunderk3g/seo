// Panel 2: per-provider grid of LLM answers. Tabs across providers,
// and inside each tab a per-query row showing the answer preview,
// whether our brand was mentioned, and the domains cited.

import { useMemo, useState } from 'react';
import type { GapLLMResultRow, GapQuery } from '../../../api/seoTypes';

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'ChatGPT',
  anthropic: 'Claude',
  google: 'Gemini',
  perplexity: 'Perplexity',
  grok: 'Grok',
};

export default function LLMResultsPanel({
  results,
  queries,
}: {
  results: GapLLMResultRow[];
  queries: GapQuery[];
}) {
  const byProvider = useMemo(() => {
    const map = new Map<string, GapLLMResultRow[]>();
    results.forEach((r) => {
      const arr = map.get(r.provider) || [];
      arr.push(r);
      map.set(r.provider, arr);
    });
    return map;
  }, [results]);

  const providers = useMemo(
    () => Array.from(byProvider.keys()).sort(),
    [byProvider],
  );
  const [active, setActive] = useState<string | null>(providers[0] ?? null);
  // Track query lookup once for inner rendering.
  const queryById = useMemo(() => {
    const m = new Map<string, GapQuery>();
    queries.forEach((q) => m.set(q.id, q));
    return m;
  }, [queries]);

  // Per-provider mention-rate strip so the summary is visible without
  // clicking through tabs.
  const summary = providers.map((p) => {
    const rows = byProvider.get(p) || [];
    const total = rows.length;
    const ok = rows.filter((r) => !r.error).length;
    const mentioned = rows.filter((r) => r.mentions_our_brand).length;
    const grounded = rows.filter((r) => r.web_search_used).length;
    return { provider: p, total, ok, mentioned, grounded };
  });

  // Effective active tab — handles the case where the active provider
  // disappears between renders (e.g. user re-runs and a key gets unset).
  const activeProvider = active && byProvider.has(active) ? active : providers[0];
  const activeRows = activeProvider ? byProvider.get(activeProvider) || [] : [];

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>What each LLM answered</h2>
        <span className="seo-card-sub">
          {results.length} probes across {providers.length} provider(s) · web
          search grounded where supported
        </span>
      </div>

      {providers.length === 0 ? (
        <div className="seo-empty">
          No LLM results yet. (Stage runs after queries are generated.)
        </div>
      ) : (
        <>
          <div className="gap-pipe-summary-row">
            {summary.map((s) => (
              <div key={s.provider} className="gap-pipe-summary-cell">
                <div className="gap-pipe-summary-label">
                  {PROVIDER_LABELS[s.provider] || s.provider}
                </div>
                <div className="gap-pipe-summary-value">
                  {s.mentioned}/{s.ok}{' '}
                  <span className="gap-pipe-summary-unit">mentions</span>
                </div>
                <div className="gap-pipe-summary-sub">
                  {s.grounded > 0 ? `${s.grounded} grounded` : 'training-only'}
                </div>
              </div>
            ))}
          </div>

          <div className="gap-pipe-tabs">
            {providers.map((p) => (
              <button
                key={p}
                type="button"
                className={`gap-pipe-tab${
                  p === activeProvider ? ' gap-pipe-tab--active' : ''
                }`}
                onClick={() => setActive(p)}
              >
                {PROVIDER_LABELS[p] || p}
                <span className="gap-pipe-tab-count">
                  {byProvider.get(p)?.length || 0}
                </span>
              </button>
            ))}
          </div>

          <table className="seo-table">
            <thead>
              <tr>
                <th>Query</th>
                <th style={{ width: 90 }}>Brand</th>
                <th style={{ width: 90 }}>Grounded</th>
                <th>Cited domains</th>
                <th>Answer preview</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="seo-empty">
                    No probes for this provider.
                  </td>
                </tr>
              ) : (
                activeRows.map((r) => {
                  const q = queryById.get(r.query_id);
                  return (
                    <tr key={r.id}>
                      <td className="seo-cell-query" title={q?.query}>
                        {q?.query || '(missing)'}
                      </td>
                      <td>
                        {r.error ? (
                          <span className="gap-pill gap-pill-skipped">
                            error
                          </span>
                        ) : r.mentions_our_brand ? (
                          <span className="gap-pill gap-pill-yes">
                            yes
                          </span>
                        ) : (
                          <span className="gap-pill gap-pill-no">no</span>
                        )}
                      </td>
                      <td>
                        {r.web_search_used ? (
                          <span className="gap-pill gap-pill-yes">web</span>
                        ) : (
                          <span className="gap-pill gap-pill-skipped">
                            model
                          </span>
                        )}
                      </td>
                      <td
                        className="seo-cell-query"
                        title={r.cited_domains.join(', ')}
                        style={{ color: 'var(--text-2)' }}
                      >
                        {r.cited_domains.slice(0, 4).join(', ') || '—'}
                        {r.cited_domains.length > 4 && (
                          <span> +{r.cited_domains.length - 4}</span>
                        )}
                      </td>
                      <td
                        className="seo-cell-query"
                        title={r.answer_text}
                        style={{ color: 'var(--text-2)' }}
                      >
                        {r.error
                          ? `(${r.error})`
                          : (r.answer_text || '').slice(0, 220) +
                            ((r.answer_text || '').length > 220 ? '…' : '')}
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
