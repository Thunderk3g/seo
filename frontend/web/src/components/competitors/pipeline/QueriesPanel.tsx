// Panel 1: the LLM-synthesised queries that drove every downstream stage.
// Users can see exactly what we asked, why, and which keywords seeded it.

import type { GapQuery } from '../../../api/seoTypes';

const INTENT_PALETTE: Record<string, string> = {
  informational: 'gap-pill-info',
  commercial: 'gap-pill-commercial',
  comparison: 'gap-pill-comparison',
  brand_specific: 'gap-pill-brand',
  long_tail: 'gap-pill-longtail',
  conversational: 'gap-pill-conv',
};

export default function QueriesPanel({
  queries,
  seedKeywordCount,
}: {
  queries: GapQuery[];
  seedKeywordCount: number;
}) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Queries we probed</h2>
        <span className="seo-card-sub">
          {queries.length} LLM-synthesised user queries · seeded from{' '}
          {seedKeywordCount} SEMrush keywords (ours + competitors')
        </span>
      </div>
      {queries.length === 0 ? (
        <div className="seo-empty">No queries have been generated yet.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Query</th>
              <th>Intent</th>
              <th>Why we asked</th>
              <th>Seeded by</th>
            </tr>
          </thead>
          <tbody>
            {queries.map((q) => (
              <tr key={q.id}>
                <td className="num" style={{ width: 32 }}>
                  {q.order + 1}
                </td>
                <td className="seo-cell-query" title={q.query}>
                  {q.query}
                </td>
                <td>
                  <span
                    className={`gap-pill ${
                      INTENT_PALETTE[q.intent] || 'gap-pill-info'
                    }`}
                  >
                    {q.intent.replace('_', ' ')}
                  </span>
                </td>
                <td
                  className="seo-cell-query"
                  title={q.rationale}
                  style={{ color: 'var(--text-2)' }}
                >
                  {q.rationale || '—'}
                </td>
                <td
                  className="seo-cell-query"
                  title={q.source_keywords.join(', ')}
                  style={{ color: 'var(--text-2)' }}
                >
                  {q.source_keywords.length
                    ? q.source_keywords.slice(0, 3).join(', ')
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
