import { useEffect, useState } from 'react';
import { Link } from 'wouter';
import Icon from './Icon';
import { crawlerApi } from '../api';

/**
 * Reports landing = a grid of square clickable blocks (one per section).
 * Clicking a block opens /crawler/reports/section/:key, which renders that
 * section's full detail (the components exported in SECTION_REGISTRY).
 *
 * Heavy sections (broken-links, external-links) do a full master scan, so
 * their data is fetched ONLY on the detail page — the landing shows a hint,
 * never triggering the scan just to render a card.
 */

// ── shared style + helpers ──────────────────────────────────────────────────
const card: React.CSSProperties = {
  background: 'var(--surface,#fff)', border: '1px solid var(--border,#e2e6ee)',
  borderRadius: 10, padding: 18, marginBottom: 18,
};
const h2: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, fontSize: 17, margin: '0 0 12px',
  color: 'var(--primary,#0b4ea2)',
};
const statRow: React.CSSProperties = { display: 'flex', gap: 22, flexWrap: 'wrap', marginBottom: 12 };
const th: React.CSSProperties = { textAlign: 'left', padding: '6px 8px', fontSize: 11, color: 'var(--muted,#6b7280)', textTransform: 'uppercase', borderBottom: '1px solid var(--border,#e2e6ee)' };
const td: React.CSSProperties = { padding: '6px 8px', fontSize: 12, borderBottom: '1px solid var(--border,#eef1f6)', verticalAlign: 'top', wordBreak: 'break-all' };

function stat(n: number | string, label: string, tone = 'var(--primary,#0b4ea2)') {
  return (
    <div key={label} style={{ textAlign: 'center', minWidth: 96 }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone }}>{n}</div>
      <div style={{ fontSize: 11, color: 'var(--muted,#6b7280)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
    </div>
  );
}
function badge(text: string, bg: string) {
  return <span style={{ background: bg, color: '#fff', borderRadius: 6, padding: '1px 7px', fontSize: 11, fontWeight: 600 }}>{text}</span>;
}
function pathOf(u: string): string { try { return new URL(u).pathname || u; } catch { return u; } }
function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div style={{ fontSize: 12, color: 'var(--muted,#6b7280)', padding: '8px 0' }}><Icon name="hourglass_empty" /> {label}</div>;
}
function Empty({ label }: { label: string }) {
  return <div style={{ fontSize: 13, color: 'var(--muted,#6b7280)', padding: '6px 0' }}>{label}</div>;
}
function SampleTable<T>({ rows, cols }: { rows: T[]; cols: Array<[string, (r: T) => React.ReactNode]> }) {
  if (!rows || rows.length === 0) return <Empty label="Nothing to show." />;
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>{cols.map(([hh]) => <th key={hh} style={th}>{hh}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map(([hh, render]) => <td key={hh} style={td}>{render(r)}</td>)}</tr>)}</tbody>
    </table>
  );
}
// generic async loader hook
function useAsync<T>(fn: () => Promise<T>): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fn().then((d) => alive && setData(d)).catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { data, error };
}

// ── per-section DETAIL components (each self-contained) ─────────────────────
const SUBDOMAIN_LABELS: Record<string, string> = {
  all: 'All',
  www: 'www',
  branch: 'Branch',
  investmentcorner: 'Investment Corner',
};

function BrokenLinksDetail() {
  const { data: broken } = useAsync(() => crawlerApi.reportBrokenLinks());
  const [sub, setSub] = useState<string>('all');
  return (
    <section style={{ ...card, borderColor: 'var(--red,#c0392b)' }}>
      <h2 style={{ ...h2, color: 'var(--red,#c0392b)' }}><Icon name="link_off" /> Broken Links — with proof of source</h2>
      {!broken ? <Loading label="Scanning every page's links for broken targets… (first run can take a minute)" />
        : broken.total_targets === 0 ? <Empty label={broken.note || 'No broken internal links found. 🎉'} /> : (
        <>
          <div style={statRow}>
            {stat(broken.total_targets, 'Broken URLs', 'var(--red,#c0392b)')}
            {stat(broken.linked_targets ?? 0, 'Linked from pages')}
            {stat(broken.total_links ?? 0, 'Broken link instances')}
          </div>
          {/* Subdomain filter — split 404s into www / branch / investment
              corner. Only shows subdomains that actually have broken URLs. */}
          {(() => {
            const bs = broken.by_subdomain || {};
            const subs = ['all', ...Object.keys(SUBDOMAIN_LABELS).filter((k) => k !== 'all' && bs[k])];
            if (subs.length <= 2) return null; // only www → no point in chips
            return (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '0 0 10px' }}>
                {subs.map((k) => {
                  const count = k === 'all' ? broken.total_targets : (bs[k]?.targets ?? 0) + (bs[k]?.orphan ?? 0);
                  const active = sub === k;
                  return (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setSub(k)}
                      style={{
                        border: '1px solid ' + (active ? 'var(--red,#c0392b)' : 'var(--border,#e2e6ee)'),
                        background: active ? 'var(--red,#c0392b)' : '#fff',
                        color: active ? '#fff' : '#334155',
                        borderRadius: 999, padding: '3px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer',
                      }}
                    >
                      {SUBDOMAIN_LABELS[k] || k} <span style={{ opacity: 0.8 }}>({count})</span>
                    </button>
                  );
                })}
              </div>
            );
          })()}
          <p style={{ fontSize: 12, color: 'var(--muted,#6b7280)', margin: '0 0 10px' }}>
            Each broken URL lists exactly which page links to it, the anchor text, section and zone — hand this to the dev/AEM team as-is.
          </p>
          {broken.targets.filter((t) => sub === 'all' || (t.subdomain || 'www') === sub).map((t) => (
            <details key={t.url} style={{ border: '1px solid var(--border,#e2e6ee)', borderRadius: 8, marginBottom: 8 }}>
              <summary style={{ padding: '8px 10px', cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {badge(t.status, 'var(--red,#c0392b)')}
                <a href={t.url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} style={{ fontSize: 12 }}>{pathOf(t.url)}</a>
                <span style={{ fontSize: 11, color: 'var(--muted,#6b7280)' }}>· linked from {t.source_count} place{t.source_count === 1 ? '' : 's'}</span>
              </summary>
              <div style={{ padding: '4px 10px 10px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Source page</th><th style={th}>Anchor text</th><th style={th}>Section</th><th style={th}>Zone</th></tr></thead>
                  <tbody>
                    {t.sources.map((s, i) => (
                      <tr key={i}>
                        <td style={td}><a href={s.page} target="_blank" rel="noreferrer">{pathOf(s.page)}</a></td>
                        <td style={td}>{s.anchor ? `“${s.anchor}”` : <em style={{ color: 'var(--muted,#9aa3b2)' }}>(no text)</em>}</td>
                        <td style={td}>{s.section || '—'}</td>
                        <td style={td}>{s.zone && badge(s.zone, 'var(--muted,#6b7280)')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ))}
        </>
      )}
    </section>
  );
}

function RedirectsDetail() {
  const { data: sec } = useAsync(() => crawlerApi.reportSections());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="alt_route" /> Redirects</h2>
      {!sec ? <Loading /> : (
        <>
          <div style={statRow}>
            {stat(sec.redirects.counts['301'], '301 Permanent')}
            {stat(sec.redirects.counts.other_3xx, 'Other 3xx', 'var(--amber,#d98e00)')}
            {stat(sec.redirects.counts.loops, 'Redirect loops', 'var(--red,#c0392b)')}
          </div>
          <SampleTable rows={sec.redirects.rows} cols={[
            ['From', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
            ['Status', (r) => badge(r.status_code, r.loop ? 'var(--red,#c0392b)' : 'var(--amber,#d98e00)')],
            ['Hops', (r) => String(r.hops)],
            ['Final URL', (r) => r.final_url ? <a href={r.final_url} target="_blank" rel="noreferrer">{pathOf(r.final_url)}</a> : '—'],
          ]} />
        </>
      )}
    </section>
  );
}

function SoftFourDetail() {
  const { data } = useAsync(() => crawlerApi.reportSoftFour());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="report_problem" /> Soft 404s <small style={{ fontWeight: 400, color: 'var(--muted)' }}>(JS-verified)</small></h2>
      <p style={{ fontSize: 12, color: 'var(--muted,#6b7280)', margin: '0 0 12px' }}>
        A soft 404 returns HTTP&nbsp;200 but has no real content. Thin pages are <strong>headless-rendered</strong>
        first — only pages that are <em>still</em> empty after JavaScript runs are flagged. JS-rendered pages
        (calculators, buy-journey flows) are excluded as false positives.
      </p>
      {!data ? (
        <Loading label="Rendering thin candidates in a headless browser… (first run can take a minute)" />
      ) : (
        <>
          <div style={statRow}>
            {stat(data.confirmed_count, 'Real soft-404s', 'var(--red,#c0392b)')}
            {stat(data.js_rendered_excluded.length, 'Excluded (JS-rendered)', 'var(--green,#1f9d55)')}
            {stat(data.candidate_count, 'Thin candidates checked')}
          </div>
          <h3 style={{ fontSize: 13, margin: '8px 0 4px', color: 'var(--red,#c0392b)' }}>Confirmed soft-404s (still empty after JS render)</h3>
          {data.confirmed.length === 0 ? <Empty label="None — every thin page rendered real content via JavaScript. 🎉" /> : (
            <SampleTable rows={data.confirmed} cols={[
              ['URL', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
              ['Server words', (r) => String(r.static_words)],
              ['Rendered words', (r) => r.rendered_words === null ? '—' : String(r.rendered_words)],
              ['Title', (r) => r.title || '—']]} />
          )}
          {data.js_rendered_excluded.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>
                {data.js_rendered_excluded.length} excluded — thin server HTML but full once JS renders (not soft-404)
              </summary>
              <SampleTable rows={data.js_rendered_excluded} cols={[
                ['URL', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
                ['Server words', (r) => String(r.static_words)],
                ['Rendered words', (r) => r.rendered_words === null ? '—' : String(r.rendered_words)]]} />
            </details>
          )}
          {data.unverified.length > 0 && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--amber,#d98e00)' }}>{data.unverified.length} could not be rendered (timeout/error) — review manually</summary>
              <SampleTable rows={data.unverified} cols={[['URL', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>], ['Server words', (r) => String(r.static_words)]]} />
            </details>
          )}
        </>
      )}
    </section>
  );
}

function SitemapDetail() {
  const { data: sec } = useAsync(() => crawlerApi.reportSections());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="account_tree" /> Sitemap coverage</h2>
      {!sec ? <Loading /> : (
        <>
          <div style={statRow}>
            {stat(sec.sitemap.counts.in_sitemap, 'In sitemap')}
            {stat(sec.sitemap.counts.discovered_only, 'Discovered only (not in sitemap)', 'var(--amber,#d98e00)')}
            {stat(sec.sitemap.counts.sitemap_errors, 'Sitemap URLs erroring', 'var(--red,#c0392b)')}
          </div>
          <details open>
            <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--amber,#d98e00)', fontWeight: 600 }}>
              {sec.sitemap.counts.discovered_only} pages found by crawling but NOT in the sitemap — candidates to add
            </summary>
            <SampleTable rows={sec.sitemap.discovered_only_rows} cols={[
              ['Page (missing from sitemap)', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
              ['Title', (r) => r.title || '—']]} />
          </details>
          {sec.sitemap.counts.sitemap_errors > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--red,#c0392b)' }}>{sec.sitemap.counts.sitemap_errors} sitemap URLs that error</summary>
              <SampleTable rows={sec.sitemap.error_rows} cols={[
                ['Sitemap URL that errors', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
                ['Status', (r) => badge(r.status_code, 'var(--red,#c0392b)')]]} />
            </details>
          )}
        </>
      )}
    </section>
  );
}

function RobotsDetail() {
  const { data: robots } = useAsync(() => crawlerApi.reportRobots());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="smart_toy" /> robots.txt</h2>
      {!robots ? <Loading /> : !robots.present ? <Empty label={`robots.txt not reachable (${robots.error || robots.status_code})`} /> : (
        <>
          <div style={statRow}>
            {stat(robots.sitemaps?.length ?? 0, 'Sitemaps declared')}
            {stat(robots.disallow_count ?? 0, 'Disallow rules')}
            {stat(robots.allow_count ?? 0, 'Allow rules')}
          </div>
          {robots.sitemaps && robots.sitemaps.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <strong style={{ fontSize: 12 }}>Sitemaps:</strong>
              <ul style={{ fontSize: 12, margin: '4px 0' }}>{robots.sitemaps.map((s) => <li key={s}><a href={s} target="_blank" rel="noreferrer">{s}</a></li>)}</ul>
            </div>
          )}
          <details><summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>View raw robots.txt</summary>
            <pre style={{ fontSize: 11, background: 'var(--bg,#f6f8fb)', padding: 10, borderRadius: 6, overflow: 'auto', maxHeight: 280 }}>{robots.raw}</pre>
          </details>
        </>
      )}
    </section>
  );
}

function TopLinkedDetail() {
  const { data: prank } = useAsync(() => crawlerApi.pagerank());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="hub" /> Top pages by internal linking</h2>
      {!prank ? <Loading /> : (
        <>
          <div style={statRow}>
            {stat(prank.summary.node_count, 'Pages in graph')}
            {stat(prank.summary.edge_count, 'Internal links')}
            {stat(prank.summary.orphan_count, 'Orphans (0 inbound)', 'var(--amber,#d98e00)')}
          </div>
          <SampleTable rows={prank.top.slice(0, 50)} cols={[
            ['Page', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
            ['Inbound', (r) => String(r.in_degree)], ['Outbound', (r) => String(r.out_degree)], ['PR score', (r) => String(r.pagerank_score)]]} />
        </>
      )}
    </section>
  );
}

function LinkingDetail() {
  const { data: sec } = useAsync(() => crawlerApi.reportSections());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="share" /> Internal &amp; external linking</h2>
      {!sec ? <Loading /> : (
        <>
          <div style={statRow}>
            {stat(sec.linking.total_internal.toLocaleString(), 'Internal links (on-page)')}
            {stat(sec.linking.total_external.toLocaleString(), 'External links')}
            {stat(sec.linking.pages_no_internal_links.length, 'Pages with 0 internal links', 'var(--amber,#d98e00)')}
          </div>
          <details open><summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>Top pages by external links</summary>
            <SampleTable rows={sec.linking.top_external_pages} cols={[
              ['Page', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
              ['External', (r) => String(r.external_links_count)], ['Internal', (r) => String(r.internal_links_count)]]} />
          </details>
          {sec.linking.pages_no_internal_links.length > 0 && (
            <details><summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>Pages with no internal links (dead-ends)</summary>
              <SampleTable rows={sec.linking.pages_no_internal_links} cols={[
                ['Page', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>], ['Title', (r) => r.title || '—']]} />
            </details>
          )}
        </>
      )}
    </section>
  );
}

function ExternalLinksDetail() {
  const { data: extlinks } = useAsync(() => crawlerApi.reportExternalLinks());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="open_in_new" /> External links — where this site links out</h2>
      <p style={{ fontSize: 12, color: 'var(--muted,#6b7280)', margin: '0 0 12px' }}>
        Every outbound link, grouped by destination domain. Expand a domain to see the exact URLs (click to open),
        and expand a URL to see which of your pages link to it.
      </p>
      {!extlinks ? <Loading label="Collecting every outbound link across the crawl… (first run can take a minute)" />
        : extlinks.total_domains === 0 ? <Empty label="No external links found." /> : (
        <>
          <div style={statRow}>
            {stat(extlinks.total_links.toLocaleString(), 'External link instances')}
            {stat(extlinks.total_unique_urls.toLocaleString(), 'Unique external URLs')}
            {stat(extlinks.total_domains.toLocaleString(), 'External domains')}
          </div>
          {extlinks.domains.map((dom) => (
            <details key={dom.domain} style={{ border: '1px solid var(--border,#e2e6ee)', borderRadius: 8, marginBottom: 6 }}>
              <summary style={{ padding: '8px 10px', cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Icon name="public" />
                <strong style={{ fontSize: 13 }}>{dom.domain || '(unknown)'}</strong>
                <span style={{ fontSize: 11, color: 'var(--muted,#6b7280)' }}>· {dom.url_count} URL{dom.url_count === 1 ? '' : 's'} · {dom.link_count} link{dom.link_count === 1 ? '' : 's'}</span>
                <a href={`https://${dom.domain}`} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} style={{ marginLeft: 'auto', fontSize: 11 }}>visit ↗</a>
              </summary>
              <div style={{ padding: '2px 10px 10px' }}>
                {dom.urls.map((u) => (
                  <details key={u.url} style={{ borderTop: '1px solid var(--border,#eef1f6)' }}>
                    <summary style={{ padding: '6px 4px', cursor: 'pointer', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <a href={u.url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} style={{ wordBreak: 'break-all' }}>{u.url}</a>
                      <span style={{ fontSize: 11, color: 'var(--muted,#6b7280)' }}>· linked {u.count}×</span>
                    </summary>
                    <div style={{ padding: '2px 0 8px 14px' }}>
                      {u.anchors.length > 0 && <div style={{ fontSize: 11, color: 'var(--muted,#6b7280)', marginBottom: 4 }}>anchors: {u.anchors.map((a) => `“${a}”`).join(', ')}</div>}
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead><tr><th style={th}>Linked from (your page)</th><th style={th}>Anchor</th><th style={th}>Zone</th><th style={th}>Rel</th></tr></thead>
                        <tbody>
                          {u.sources.map((s, i) => (
                            <tr key={i}>
                              <td style={td}><a href={s.page} target="_blank" rel="noreferrer">{pathOf(s.page)}</a></td>
                              <td style={td}>{s.anchor ? `“${s.anchor}”` : '—'}</td>
                              <td style={td}>{s.zone && badge(s.zone, 'var(--muted,#6b7280)')}</td>
                              <td style={td}>{s.rel || 'follow'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                ))}
              </div>
            </details>
          ))}
        </>
      )}
    </section>
  );
}

function PdfDetail() {
  const { data: sec } = useAsync(() => crawlerApi.reportSections());
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="picture_as_pdf" /> PDF health</h2>
      {!sec ? <Loading /> : sec.pdf.counts.total === 0 ? <Empty label="No PDFs found in the crawl." /> : (
        <>
          <div style={statRow}>
            {stat(sec.pdf.counts.total, 'PDFs')}
            {stat(sec.pdf.counts.ok, 'OK', 'var(--green,#1f9d55)')}
            {stat(sec.pdf.counts.error, 'With errors', 'var(--red,#c0392b)')}
            {stat(sec.pdf.counts.broken, 'Broken (non-200)', 'var(--red,#c0392b)')}
            {stat(sec.pdf.counts.encrypted, 'Encrypted', 'var(--amber,#d98e00)')}
            {stat(sec.pdf.counts.no_text_layer, 'No text layer', 'var(--amber,#d98e00)')}
          </div>
          <SampleTable rows={sec.pdf.rows} cols={[
            ['PDF', (r) => <a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a>],
            ['Status', (r) => r.has_error ? badge(r.reasons.join(', ') || 'error', 'var(--red,#c0392b)') : badge('ok', 'var(--green,#1f9d55)')],
            ['Pages', (r) => String(r.pages || '—')],
            ['Size', (r) => r.byte_size ? `${Math.round(r.byte_size / 1024)} KB` : '—']]} />
        </>
      )}
    </section>
  );
}

function BacklinksDetail() {
  const { data: backlinks } = useAsync(() => crawlerApi.backlinks(100));
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="input" /> Backlinks <small style={{ fontWeight: 400, color: 'var(--muted)' }}>(own-domain inbound)</small></h2>
      {!backlinks ? <Loading /> : backlinks.summary.total === 0 ? (
        <Empty label="No backlinks discovered yet — the own-domain backlink discovery pipeline hasn't been run/built." />
      ) : (
        <>
          <div style={statRow}>{stat(backlinks.summary.total, 'Backlinks')}{stat(backlinks.summary.top_referring_domains.length, 'Referring domains')}</div>
          <SampleTable rows={backlinks.backlinks} cols={[
            ['From', (r) => <a href={r.source_url} target="_blank" rel="noreferrer">{r.source_domain}</a>],
            ['To', (r) => <a href={r.target_url} target="_blank" rel="noreferrer">{pathOf(r.target_url)}</a>],
            ['Anchor', (r) => r.anchor_text || '—'], ['Rel', (r) => r.nofollow ? badge('nofollow', 'var(--muted)') : 'follow']]} />
        </>
      )}
    </section>
  );
}

const CWV_TONE: Record<string, string> = {
  good: 'var(--green,#1f9d55)', needs_improvement: 'var(--amber,#d98e00)', poor: 'var(--red,#c0392b)',
};
const CWV_CHIP_BG: Record<string, string> = { good: '#E6F4EA', needs_improvement: '#FEF7E0', poor: '#FCE8E6' };
const CWV_CHIP_FG: Record<string, string> = { good: '#137333', needs_improvement: '#B06000', poor: '#C5221F' };
function cwvCell(value: number | null, bucket: string | null, kind: 'lcp' | 'cls' | 'inp') {
  if (value === null || value === undefined) return <span style={{ color: 'var(--muted,#9aa3b2)' }}>—</span>;
  const text = kind === 'lcp' ? `${(value / 1000).toFixed(2)} s` : kind === 'cls' ? value.toFixed(2) : `${Math.round(value)} ms`;
  return (
    <span style={{
      background: bucket ? CWV_CHIP_BG[bucket] : 'transparent',
      color: bucket ? CWV_CHIP_FG[bucket] : 'inherit',
      borderRadius: 6, padding: '2px 8px', fontWeight: 600, fontSize: 12,
      display: 'inline-block', minWidth: 56, textAlign: 'center',
    }}>{text}</span>
  );
}
const thGroup: React.CSSProperties = { ...th, textAlign: 'center', borderBottom: 'none', paddingBottom: 2 };
const thSub: React.CSSProperties = { ...th, textAlign: 'center', fontSize: 10, paddingTop: 0 };
function CwvBar({ b }: { b: { good: number; needs_improvement: number; poor: number } }) {
  const total = b.good + b.needs_improvement + b.poor || 1;
  const seg = (n: number, c: string) => n > 0 ? <span style={{ width: `${(n / total) * 100}%`, background: c, display: 'inline-block', height: 10 }} title={`${n}`} /> : null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ display: 'flex', flex: 1, borderRadius: 4, overflow: 'hidden', minWidth: 120, border: '1px solid var(--border,#e2e6ee)' }}>
        {seg(b.good, CWV_TONE.good)}{seg(b.needs_improvement, CWV_TONE.needs_improvement)}{seg(b.poor, CWV_TONE.poor)}
      </div>
      <span style={{ fontSize: 11, color: 'var(--muted,#6b7280)' }}>{b.good} good · {b.needs_improvement} NI · {b.poor} poor</span>
    </div>
  );
}
function CwvDetail() {
  const { data } = useAsync(() => crawlerApi.reportCwv());
  const strategies: Array<'mobile' | 'desktop'> = ['mobile', 'desktop'];
  return (
    <section style={card}>
      <h2 style={h2}><Icon name="speed" /> Core Web Vitals <small style={{ fontWeight: 400, color: 'var(--muted)' }}>(mobile + desktop)</small></h2>
      <p style={{ fontSize: 12, color: 'var(--muted,#6b7280)', margin: '0 0 12px' }}>
        From the PageSpeed Insights API. Where available these are <strong>real-user field data</strong> (CrUX) — the
        same signal Google ranks on (mobile). Good ≤ 2.5 s LCP · ≤ 0.1 CLS · ≤ 200 ms INP.
      </p>
      {!data ? <Loading /> : data.pages_with_cwv === 0 ? (
        <Empty label="No CWV data yet — PageSpeed runs during the crawl; re-check after it finishes." />
      ) : (
        <>
          <div style={statRow}>
            {stat(data.pages_with_cwv, 'Pages with CWV')}
            {stat(data.field_data_pages, 'With real-user field data', 'var(--green,#1f9d55)')}
          </div>
          {strategies.map((strat) => (
            <div key={strat} style={{ marginBottom: 12 }}>
              <h3 style={{ fontSize: 13, margin: '6px 0', textTransform: 'capitalize', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon name={strat === 'mobile' ? 'smartphone' : 'desktop_windows'} /> {strat}
                {strat === 'mobile' && <span style={{ fontSize: 10, background: 'var(--primary-light,#eaf1fb)', color: 'var(--primary)', borderRadius: 4, padding: '1px 6px' }}>ranking signal</span>}
              </h3>
              {(['lcp', 'cls', 'inp'] as const).map((mtr) => (
                <div key={mtr} style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '3px 0' }}>
                  <span style={{ width: 38, fontSize: 11, textTransform: 'uppercase', color: 'var(--muted,#6b7280)' }}>{mtr}</span>
                  <CwvBar b={data.summary[strat][mtr]} />
                </div>
              ))}
            </div>
          ))}
          <h3 style={{ fontSize: 13, margin: '10px 0 4px' }}>Per page <small style={{ fontWeight: 400, color: 'var(--muted)' }}>(worst mobile first)</small></h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...thGroup, textAlign: 'left' }} rowSpan={2}>Page</th>
                <th style={thGroup} colSpan={3}><Icon name="smartphone" /> Mobile</th>
                <th style={thGroup} colSpan={3}><Icon name="desktop_windows" /> Desktop</th>
                <th style={thGroup} rowSpan={2}>Source</th>
              </tr>
              <tr>
                <th style={thSub}>LCP</th><th style={thSub}>CLS</th><th style={thSub}>INP</th>
                <th style={thSub}>LCP</th><th style={thSub}>CLS</th><th style={thSub}>INP</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i}>
                  <td style={td}><a href={r.url} target="_blank" rel="noreferrer">{pathOf(r.url)}</a></td>
                  <td style={td}>{cwvCell(r.mobile.lcp_ms, r.mobile.lcp_bucket, 'lcp')}</td>
                  <td style={td}>{cwvCell(r.mobile.cls, r.mobile.cls_bucket, 'cls')}</td>
                  <td style={td}>{cwvCell(r.mobile.inp_ms, r.mobile.inp_bucket, 'inp')}</td>
                  <td style={td}>{cwvCell(r.desktop.lcp_ms, r.desktop.lcp_bucket, 'lcp')}</td>
                  <td style={td}>{cwvCell(r.desktop.cls, r.desktop.cls_bucket, 'cls')}</td>
                  <td style={td}>{cwvCell(r.desktop.inp_ms, r.desktop.inp_bucket, 'inp')}</td>
                  <td style={td}>{(r.mobile.field_data || r.desktop.field_data) ? badge('field', 'var(--green,#1f9d55)') : badge('lab', 'var(--muted,#6b7280)')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

// ── registry (shared by the card grid + the detail route) ───────────────────
export interface SectionDef {
  key: string; title: string; icon: string; tone: string; blurb: string;
  heavy?: boolean; Detail: React.FC;
}
export const SECTION_REGISTRY: Record<string, SectionDef> = {
  'broken-links': { key: 'broken-links', title: 'Broken Links', icon: 'link_off', tone: 'var(--red,#c0392b)', blurb: 'Every 404 with proof of the page + anchor that links it.', heavy: true, Detail: BrokenLinksDetail },
  redirects: { key: 'redirects', title: 'Redirects', icon: 'alt_route', tone: 'var(--amber,#d98e00)', blurb: '301 / 3xx / redirect loops.', Detail: RedirectsDetail },
  'soft-404': { key: 'soft-404', title: 'Soft 404s', icon: 'report_problem', tone: 'var(--amber,#d98e00)', blurb: 'JS-verified: thin even after rendering.', heavy: true, Detail: SoftFourDetail },
  sitemap: { key: 'sitemap', title: 'Sitemap coverage', icon: 'account_tree', tone: 'var(--primary,#0b4ea2)', blurb: 'In-sitemap vs discovered, sitemap errors.', Detail: SitemapDetail },
  robots: { key: 'robots', title: 'robots.txt', icon: 'smart_toy', tone: 'var(--primary,#0b4ea2)', blurb: 'Declared sitemaps + disallow/allow rules.', Detail: RobotsDetail },
  cwv: { key: 'cwv', title: 'Core Web Vitals', icon: 'speed', tone: 'var(--primary,#0b4ea2)', blurb: 'LCP / CLS / INP — mobile + desktop.', Detail: CwvDetail },
  'top-linked': { key: 'top-linked', title: 'Top internal linking', icon: 'hub', tone: 'var(--primary,#0b4ea2)', blurb: 'Most-linked pages + orphans.', Detail: TopLinkedDetail },
  linking: { key: 'linking', title: 'Internal & external linking', icon: 'share', tone: 'var(--primary,#0b4ea2)', blurb: 'Link totals + dead-end pages.', Detail: LinkingDetail },
  'external-links': { key: 'external-links', title: 'External links', icon: 'open_in_new', tone: 'var(--primary,#0b4ea2)', blurb: 'Outbound links by domain → URL → page.', heavy: true, Detail: ExternalLinksDetail },
  pdf: { key: 'pdf', title: 'PDF health', icon: 'picture_as_pdf', tone: 'var(--primary,#0b4ea2)', blurb: 'Broken / encrypted / no-text-layer PDFs.', Detail: PdfDetail },
  backlinks: { key: 'backlinks', title: 'Backlinks', icon: 'input', tone: 'var(--primary,#0b4ea2)', blurb: 'Own-domain inbound links.', Detail: BacklinksDetail },
};
export const SECTION_ORDER = ['broken-links', 'cwv', 'redirects', 'soft-404', 'sitemap', 'robots', 'top-linked', 'linking', 'external-links', 'pdf', 'backlinks'];

// ── the landing: grid of square clickable blocks ────────────────────────────
export default function ReportSectionsPanel() {
  // light fetches only — never the heavy master scans (those run on the detail page)
  const { data: sec } = useAsync(() => crawlerApi.reportSections());
  const { data: robots } = useAsync(() => crawlerApi.reportRobots());
  const { data: prank } = useAsync(() => crawlerApi.pagerank());
  const { data: backlinks } = useAsync(() => crawlerApi.backlinks(1));
  const { data: cwvData } = useAsync(() => crawlerApi.reportCwv());

  function summary(key: string): { count: string; sub: string } | null {
    switch (key) {
      case 'cwv': {
        if (!cwvData) return null;
        const m = cwvData.summary.mobile.lcp;
        const tot = m.good + m.needs_improvement + m.poor;
        return { count: tot ? `${Math.round((m.good / tot) * 100)}%` : '—', sub: 'mobile LCP good' };
      }
      case 'redirects': return sec ? { count: String(sec.redirects.counts['301'] + sec.redirects.counts.other_3xx + sec.redirects.counts.loops), sub: 'redirecting URLs' } : null;
      case 'sitemap': return sec ? { count: sec.sitemap.counts.in_sitemap.toLocaleString(), sub: 'URLs in sitemap' } : null;
      case 'robots': return robots ? { count: String(robots.sitemaps?.length ?? 0), sub: 'sitemaps declared' } : null;
      case 'top-linked': return prank ? { count: prank.summary.orphan_count.toLocaleString(), sub: 'orphan pages' } : null;
      case 'linking': return sec ? { count: sec.linking.total_external.toLocaleString(), sub: 'external links' } : null;
      case 'pdf': return sec ? { count: String(sec.pdf.counts.total), sub: `${sec.pdf.counts.error} with errors` } : null;
      case 'backlinks': return backlinks ? { count: String(backlinks.summary.total), sub: 'backlinks' } : null;
      default: return null; // heavy sections: no number on the landing
    }
  }

  return (
    <div className="cc-section-grid">
      {SECTION_ORDER.map((key) => {
        const def = SECTION_REGISTRY[key];
        const s = summary(key);
        return (
          <Link key={key} href={`/crawler/reports/section/${key}`} className="cc-section-card">
            <div className="sc-icon" style={{ color: def.tone, background: 'var(--primary-light,#eaf1fb)' }}><Icon name={def.icon} /></div>
            <div className="sc-title">{def.title}</div>
            {def.heavy
              ? <div style={{ fontSize: 12, color: 'var(--muted,#6b7280)' }}>{def.blurb}</div>
              : <div className="sc-count" style={{ color: def.tone }}>{s ? s.count : '…'}</div>}
            <div className="sc-sub">{def.heavy ? 'Open to scan →' : (s ? s.sub : def.blurb)}</div>
            <div className="sc-open"><Icon name="arrow_forward" /> Open section</div>
          </Link>
        );
      })}
    </div>
  );
}
