// Panel 5: deep-crawl profile for each top-10 competitor + our own site.
// Each row is one domain; columns are the profile metrics aggregated
// from CompetitorCrawler results. Click the chevron to expand the row
// and inspect every sampled page's content (URL, title, meta, H1, and
// a collapsible body excerpt). No side-by-side comparison here — the
// assistant page does that via prompts to the chat agent.

import { Fragment, useState } from 'react';
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

// One sample page rendered inside the expanded row. Body excerpt is
// collapsed to 600 chars by default; click "show full" to see the full
// 200 KB captured body (rare to need but no need to gatekeep it).
function SamplePageRow({
  page,
}: {
  page: NonNullable<GapDeepCrawlRow['profile']>['sample_pages'] extends
    | Array<infer T>
    | undefined
    ? T
    : never;
}) {
  const [showFull, setShowFull] = useState(false);
  const body = page.body_text || '';
  const cap = 600;
  const truncated = body.length > cap;
  const displayed = showFull || !truncated ? body : body.slice(0, cap) + '…';

  return (
    <div
      style={{
        padding: '12px 16px',
        borderTop: '1px solid var(--border-1)',
        background: 'var(--surface-2)',
      }}
    >
      <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', marginBottom: 6 }}>
        <a
          href={page.url}
          target="_blank"
          rel="noreferrer"
          style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-2)' }}
        >
          {page.url}
        </a>
        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
          {page.page_type} · {fmt(page.word_count)} words
          {page.pagespeed_score !== null && page.pagespeed_score !== undefined && (
            <> · PageSpeed {page.pagespeed_score}</>
          )}
          {page.lcp_ms ? <> · LCP {fmt(page.lcp_ms, 'ms')}</> : null}
        </span>
      </div>
      {page.title && (
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{page.title}</div>
      )}
      {page.meta_description && (
        <div style={{ color: 'var(--text-2)', fontSize: 13, marginBottom: 6 }}>
          <span style={{ color: 'var(--text-3)', fontSize: 11 }}>META</span>{' '}
          {page.meta_description}
        </div>
      )}
      {page.h1_texts && page.h1_texts.length > 0 && (
        <div style={{ fontSize: 13, marginBottom: 6 }}>
          <span style={{ color: 'var(--text-3)', fontSize: 11 }}>H1</span>{' '}
          {page.h1_texts.join(' · ')}
        </div>
      )}
      {page.schema_types && page.schema_types.length > 0 && (
        <div style={{ fontSize: 12, marginBottom: 6, color: 'var(--text-2)' }}>
          <span style={{ color: 'var(--text-3)', fontSize: 11 }}>SCHEMA</span>{' '}
          {page.schema_types.map((t) => (
            <span
              key={t}
              style={{
                display: 'inline-block',
                padding: '1px 6px',
                margin: '0 4px 2px 0',
                background: 'var(--surface-3)',
                borderRadius: 3,
                fontSize: 11,
              }}
            >
              {t}
            </span>
          ))}
        </div>
      )}
      {body && (
        <div>
          <div style={{ color: 'var(--text-3)', fontSize: 11, marginBottom: 4 }}>
            BODY ({body.length.toLocaleString()} chars captured)
          </div>
          <div
            style={{
              fontSize: 13,
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              background: 'var(--surface-1)',
              padding: '8px 12px',
              borderRadius: 4,
              maxHeight: showFull ? 'none' : 220,
              overflow: 'auto',
            }}
          >
            {displayed}
          </div>
          {truncated && (
            <button
              type="button"
              onClick={() => setShowFull(!showFull)}
              style={{
                marginTop: 6,
                background: 'transparent',
                border: '1px solid var(--border-1)',
                borderRadius: 4,
                padding: '4px 10px',
                fontSize: 12,
                cursor: 'pointer',
                color: 'var(--text-2)',
              }}
            >
              {showFull ? 'Show less' : `Show full (${body.length.toLocaleString()} chars)`}
            </button>
          )}
        </div>
      )}
      {!body && (
        <div style={{ color: 'var(--text-3)', fontSize: 12, fontStyle: 'italic' }}>
          No body text captured (re-run gap pipeline with the new schema
          to populate).
        </div>
      )}
    </div>
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

  // Track which domains have their sample-pages drawer expanded.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Deep crawl profile</h2>
        <span className="seo-card-sub">
          What we found on each competitor (and ourselves) — sitemap +
          per-page schema / wordcount / response time. Click a row to
          inspect every sampled page's content.
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
              <th style={{ width: 28 }}></th>
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
            </tr>
          </thead>
          <tbody>
            {ordered.map((c) => {
              const isOpen = expanded.has(c.id);
              const samples = c.profile?.sample_pages || [];
              const hasSamples = samples.length > 0;
              return (
                <Fragment key={c.id}>
                  <tr
                    className={c.is_us ? 'gap-pipe-us-row' : ''}
                    onClick={() => hasSamples && toggle(c.id)}
                    style={{ cursor: hasSamples ? 'pointer' : 'default' }}
                  >
                    <td
                      style={{
                        textAlign: 'center',
                        color: 'var(--text-3)',
                        userSelect: 'none',
                      }}
                      title={
                        hasSamples
                          ? `${samples.length} sample pages`
                          : 'no samples captured'
                      }
                    >
                      {hasSamples ? (isOpen ? '▼' : '▶') : ''}
                    </td>
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
                        onClick={(e) => e.stopPropagation()}
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
                    <td className="num" title="Mobile Lighthouse perf score (0-100). PSI-derived.">
                      {fmt(c.profile?.avg_pagespeed_score)}
                    </td>
                    <td className="num" title="Median mobile Largest Contentful Paint (lower = better). CrUX p75 when available, else lab.">
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
                    <td className="num" title="Median mobile Interaction to Next Paint (lower = better). Real-user only — blank when no CrUX data.">
                      {fmt(c.profile?.median_inp_ms, ' ms')}
                    </td>
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
                  {isOpen && hasSamples && (
                    <tr>
                      <td colSpan={14} style={{ padding: 0 }}>
                        <div
                          style={{
                            background: 'var(--surface-2)',
                            borderTop: '2px solid var(--accent-1, #1565c0)',
                          }}
                        >
                          <div
                            style={{
                              padding: '8px 16px',
                              fontSize: 12,
                              color: 'var(--text-2)',
                              borderBottom: '1px solid var(--border-1)',
                            }}
                          >
                            {samples.length} sample page
                            {samples.length === 1 ? '' : 's'} captured from{' '}
                            <b>{c.domain}</b>
                          </div>
                          {samples.map((s) => (
                            <SamplePageRow key={s.url} page={s} />
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
