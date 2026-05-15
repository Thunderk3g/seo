// Panel 6 (the only "outcome" panel): the gap rows produced by stage 6.
// Each row is one dimension where we're behind the rival median, sorted
// by severity. This is the *answer* the rest of the pipeline builds up to.

import type { GapComparisonRow } from '../../../api/seoTypes';

const DIMENSION_LABELS: Record<string, string> = {
  content_depth: 'Content depth',
  schema_coverage: 'Schema coverage',
  h1_coverage: 'H1 coverage',
  response_time: 'Response time',
  page_type_coverage: 'Page-type coverage',
  machine_readable: 'Machine-readable signals',
  ai_citability: 'AI citability',
  llm_visibility: 'LLM visibility',
  serp_visibility: 'SERP visibility',
};

export default function ComparisonPanel({
  rows,
}: {
  rows: GapComparisonRow[];
}) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Where we lag</h2>
        <span className="seo-card-sub">
          Per-dimension gap vs the rival median (computed from the deep
          crawls above + the LLM/SERP visibility above)
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">
          No gaps found in the dimensions we measure. (Or comparison hasn't
          finished yet.)
        </div>
      ) : (
        <div className="gap-card-findings">
          {rows.map((r) => (
            <div
              key={r.id}
              className={`gap-finding sev-${r.severity}`}
            >
              <div className="gap-finding-head">
                <span className={`gap-sev gap-sev-${r.severity}`}>
                  {r.severity}
                </span>
                <span className="gap-pill gap-pill-info">
                  {DIMENSION_LABELS[r.dimension] || r.dimension}
                </span>
                <span style={{ flex: 1 }}>{r.headline}</span>
              </div>
              {Object.keys(r.our_value).length > 0 && (
                <div
                  style={{
                    color: 'var(--text-2)',
                    fontSize: 12,
                    marginTop: 4,
                  }}
                >
                  Ours: <code>{JSON.stringify(r.our_value)}</code>
                  {Object.keys(r.competitor_median).length > 0 && (
                    <>
                      {' '}
                      · Rival median:{' '}
                      <code>{JSON.stringify(r.competitor_median)}</code>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
