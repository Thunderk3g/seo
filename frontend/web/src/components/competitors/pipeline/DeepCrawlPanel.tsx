// Panel 5: deep-crawl profile for each top-10 competitor + our own site.
// Each row is one domain; columns are the profile metrics aggregated
// from CompetitorCrawler results.

import type { GapDeepCrawlRow } from '../../../api/seoTypes';

function fmt(n: number | undefined, suffix = ''): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '—';
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k${suffix}`;
  return `${Math.round(n)}${suffix}`;
}

function PageTypeCounts({
  pt,
}: {
  pt?: Record<string, number>;
}) {
  if (!pt) return <span>—</span>;
  const keys: { key: string; short: string }[] = [
    { key: 'pricing', short: 'price' },
    { key: 'comparison', short: 'comp' },
    { key: 'calculator', short: 'calc' },
    { key: 'faq', short: 'faq' },
    { key: 'blog', short: 'blog' },
  ];
  const parts = keys
    .map((k) => ({ ...k, value: pt[k.key] || 0 }))
    .filter((k) => k.value > 0);
  if (parts.length === 0) return <span style={{ color: 'var(--text-3)' }}>none</span>;
  return (
    <span style={{ color: 'var(--text-2)' }}>
      {parts.map((p, i) => (
        <span key={p.key}>
          {i > 0 && ' · '}
          {p.short} {p.value}
        </span>
      ))}
    </span>
  );
}

export default function DeepCrawlPanel({
  rows,
}: {
  rows: GapDeepCrawlRow[];
}) {
  // Sort: us first, then by ai_citability_score descending.
  const ordered = [...rows].sort((a, b) => {
    if (a.is_us !== b.is_us) return a.is_us ? -1 : 1;
    return (
      (b.profile?.ai_citability_score || 0) -
      (a.profile?.ai_citability_score || 0)
    );
  });

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Deep crawl profile</h2>
        <span className="seo-card-sub">
          What we found on each competitor (and ourselves) — sitemap +
          per-page schema / wordcount / response time
        </span>
      </div>
      {ordered.length === 0 ? (
        <div className="seo-empty">
          Crawl hasn't run yet. (Stage runs after top-10 are picked.)
        </div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Domain</th>
              <th className="num">Sitemap URLs</th>
              <th className="num">Crawled OK</th>
              <th className="num">Avg words</th>
              <th className="num">Schema %</th>
              <th className="num">Avg response</th>
              <th className="num">AI citability</th>
              <th>Page types</th>
              <th>Signals</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((c) => (
              <tr key={c.id} className={c.is_us ? 'gap-pipe-us-row' : ''}>
                <td className="seo-cell-query">
                  {c.is_us && (
                    <span className="gap-pill gap-pill-yes" style={{ marginRight: 8 }}>
                      us
                    </span>
                  )}
                  <a
                    href={`https://${c.domain}/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {c.domain}
                  </a>
                </td>
                <td className="num">{fmt(c.sitemap_url_count)}</td>
                <td className="num">
                  {c.pages_ok}/{c.pages_attempted}
                </td>
                <td className="num">{fmt(c.profile?.avg_word_count)}</td>
                <td className="num">{fmt(c.profile?.schema_pct, '%')}</td>
                <td className="num">{fmt(c.profile?.avg_response_ms, ' ms')}</td>
                <td className="num">
                  {fmt(c.profile?.ai_citability_score)}
                </td>
                <td>
                  <PageTypeCounts pt={c.profile?.page_types} />
                </td>
                <td style={{ fontSize: 12, color: 'var(--text-2)' }}>
                  {c.profile?.has_llms_txt && <span>llms.txt </span>}
                  {c.profile?.has_pricing_md && <span>pricing.md </span>}
                  {c.profile?.has_pricing_page && <span>/pricing </span>}
                  {!c.profile?.has_llms_txt &&
                    !c.profile?.has_pricing_md &&
                    !c.profile?.has_pricing_page && <span>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
