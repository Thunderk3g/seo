// Panel 5 — deep-crawl profile per competitor (Phase 2 rewrite).
//
// PHASE 2 CHANGE: dropped the expandable-rows "dropdown" inline body
// view. Each competitor row is now a clickable card that routes to
// /competitors/<domain>/ — a proper page with the full profile + a
// per-URL sample-pages table. Per-URL detail opens in a new tab from
// there, so the operator can keep the comparison side-by-side.
//
// No emojis. Bajaj brand via existing seo-card classes (this component
// still lives inside the legacy lattice.css cascade, not bajaj-ui).

import { Link } from 'wouter';
import type { GapDeepCrawlRow } from '../../../api/seoTypes';

function fmt(n: number | undefined, suffix = ''): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '—';
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k${suffix}`;
  return `${Math.round(n)}${suffix}`;
}

function PageTypeCounts({ pt }: { pt?: Record<string, number> }) {
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

export default function DeepCrawlPanel({ rows }: { rows: GapDeepCrawlRow[] }) {
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
          per-page schema / wordcount / response time. Click a row to
          open the full per-competitor view with every captured page.
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
              <th className="num">PageSpeed</th>
              <th className="num">LCP</th>
              <th className="num">CLS</th>
              <th className="num">INP</th>
              <th className="num">AI citability</th>
              <th>Page types</th>
              <th>Signals</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {ordered.map((c) => (
              <tr key={c.id} className={c.is_us ? 'gap-pipe-us-row' : ''}>
                <td className="seo-cell-query">
                  {c.is_us && (
                    <span
                      className="gap-pill gap-pill-yes"
                      style={{ marginRight: 8 }}
                    >
                      us
                    </span>
                  )}
                  <Link href={`/competitors/${encodeURIComponent(c.domain)}`}>
                    <a
                      style={{
                        color: 'var(--accent)',
                        textDecoration: 'none',
                        fontWeight: 500,
                      }}
                    >
                      {c.domain}
                    </a>
                  </Link>
                </td>
                <td className="num">{fmt(c.sitemap_url_count)}</td>
                <td className="num">
                  {c.pages_ok}/{c.pages_attempted}
                </td>
                <td className="num">{fmt(c.profile?.avg_word_count)}</td>
                <td className="num">{fmt(c.profile?.schema_pct, '%')}</td>
                <td className="num">{fmt(c.profile?.avg_response_ms, ' ms')}</td>
                <td
                  className="num"
                  title="Mobile Lighthouse perf score (0-100). PSI-derived."
                >
                  {fmt(c.profile?.avg_pagespeed_score)}
                </td>
                <td
                  className="num"
                  title="Median mobile Largest Contentful Paint (lower = better). CrUX p75 when available, else lab."
                >
                  {fmt(c.profile?.median_lcp_ms, ' ms')}
                </td>
                <td
                  className="num"
                  title="Median mobile Cumulative Layout Shift (lower = better)."
                >
                  {c.profile?.median_cls !== undefined && c.profile?.median_cls !== null
                    ? c.profile.median_cls.toFixed(3)
                    : '—'}
                </td>
                <td
                  className="num"
                  title="Median mobile Interaction to Next Paint (lower = better). Real-user only — blank when no CrUX data."
                >
                  {fmt(c.profile?.median_inp_ms, ' ms')}
                </td>
                <td className="num">{fmt(c.profile?.ai_citability_score)}</td>
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
                <td style={{ textAlign: 'right' }}>
                  <Link href={`/competitors/${encodeURIComponent(c.domain)}`}>
                    <a
                      style={{
                        color: 'var(--accent)',
                        textDecoration: 'none',
                        fontSize: 12,
                        fontWeight: 500,
                      }}
                    >
                      Open →
                    </a>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
