// SubScoreGrid — 4×2 grid of named sub-scores. Each card colour-codes
// by band so the eye can scan it without reading every number.
//
// `entries` is passed in (rather than derived) so the same component
// can render both the deterministic scoring output (`SEORunSubScores`)
// and a partial subset on the dashboard.

interface Entry {
  key: string;
  label: string;
  value: number | undefined | null;
}

function band(v: number): 'good' | 'warn' | 'bad' | '' {
  if (v >= 80) return 'good';
  if (v >= 50) return '';
  if (v >= 30) return 'warn';
  return 'bad';
}

export default function SubScoreGrid({ entries }: { entries: Entry[] }) {
  return (
    <div className="seo-subscores">
      {entries.map((e) => {
        const v = typeof e.value === 'number' ? e.value : 0;
        const cls = band(v);
        return (
          <div key={e.key} className={`seo-subscore ${cls}`}>
            <div className="seo-subscore-label">{e.label}</div>
            <div className="seo-subscore-value">
              {typeof e.value === 'number' ? Math.round(v) : '—'}
            </div>
            <div className="seo-subscore-bar">
              <div style={{ width: `${Math.max(2, Math.min(100, v))}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export const SUB_SCORE_LABELS: Record<string, string> = {
  technical: 'Technical',
  content: 'Content',
  backlinks: 'Backlinks',
  core_web_vitals: 'Core Web Vitals',
  internal_linking: 'Internal Linking',
  serp_ctr: 'SERP CTR',
  structured_data: 'Structured Data',
  indexability: 'Indexability',
};
