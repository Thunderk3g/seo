import { useEffect, useState } from 'react';
import Icon from './Icon';
import { crawlerApi } from '../api';

type Sections = Awaited<ReturnType<typeof crawlerApi.reportSections>>;
type Broken = Awaited<ReturnType<typeof crawlerApi.reportBrokenLinks>>;
type Robots = Awaited<ReturnType<typeof crawlerApi.reportRobots>>;
type Pagerank = Awaited<ReturnType<typeof crawlerApi.pagerank>>;
type Backlinks = Awaited<ReturnType<typeof crawlerApi.backlinks>>;
type ExtLinks = Awaited<ReturnType<typeof crawlerApi.reportExternalLinks>>;

const card: React.CSSProperties = {
  background: 'var(--surface, #fff)',
  border: '1px solid var(--border, #e2e6ee)',
  borderRadius: 10,
  padding: 18,
  marginBottom: 18,
};
const h2: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8,
  fontSize: 16, margin: '0 0 12px', color: 'var(--primary, #0b4ea2)',
};
const stat = (n: number | string, label: string, tone = 'var(--primary,#0b4ea2)') => (
  <div key={label} style={{ textAlign: 'center', minWidth: 96 }}>
    <div style={{ fontSize: 22, fontWeight: 700, color: tone }}>{n}</div>
    <div style={{ fontSize: 11, color: 'var(--muted,#6b7280)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
  </div>
);
const statRow: React.CSSProperties = { display: 'flex', gap: 22, flexWrap: 'wrap', marginBottom: 12 };
const th: React.CSSProperties = { textAlign: 'left', padding: '6px 8px', fontSize: 11, color: 'var(--muted,#6b7280)', textTransform: 'uppercase', borderBottom: '1px solid var(--border,#e2e6ee)' };
const td: React.CSSProperties = { padding: '6px 8px', fontSize: 12, borderBottom: '1px solid var(--border,#eef1f6)', verticalAlign: 'top', wordBreak: 'break-all' };
const badge = (text: string, bg: string) => (
  <span style={{ background: bg, color: '#fff', borderRadius: 6, padding: '1px 7px', fontSize: 11, fontWeight: 600 }}>{text}</span>
);

function pathOf(u: string): string {
  try { return new URL(u).pathname || u; } catch { return u; }
}

export default function ReportSectionsPanel() {
  const [sec, setSec] = useState<Sections | null>(null);
  const [broken, setBroken] = useState<Broken | null>(null);
  const [robots, setRobots] = useState<Robots | null>(null);
  const [prank, setPrank] = useState<Pagerank | null>(null);
  const [backlinks, setBacklinks] = useState<Backlinks | null>(null);
  const [extlinks, setExtlinks] = useState<ExtLinks | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // Sections + broken-links can be slow on the first call after a crawl
    // (lean rebuild / master scan); load each independently so a slow one
    // never blocks the rest of the page.
    crawlerApi.reportSections().then((d) => alive && setSec(d)).catch((e) => alive && setErr(String(e)));
    crawlerApi.reportRobots().then((d) => alive && setRobots(d)).catch(() => {});
    crawlerApi.pagerank().then((d) => alive && setPrank(d)).catch(() => {});
    crawlerApi.backlinks(50).then((d) => alive && setBacklinks(d)).catch(() => {});
    crawlerApi.reportExternalLinks().then((d) => alive && setExtlinks(d)).catch(() => {});
    crawlerApi.reportBrokenLinks().then((d) => alive && setBroken(d)).catch(() => {});
    return () => { alive = false; };
  }, []);

  return (
    <div>
      {err && <div style={{ ...card, borderColor: 'var(--red,#c0392b)', color: 'var(--red,#c0392b)' }}><Icon name="error" /> {err}</div>}

      {/* ── 1. Broken links (with proof) — the headline section ───────── */}
      <section style={{ ...card, borderColor: 'var(--red,#c0392b)' }}>
        <h2 style={{ ...h2, color: 'var(--red,#c0392b)' }}><Icon name="link_off" /> Broken Links — with proof of source</h2>
        {!broken ? (
          <Loading label="Scanning every page's links for broken targets…" />
        ) : broken.total_targets === 0 ? (
          <Empty label={broken.note || 'No broken internal links found. 🎉'} />
        ) : (
          <>
            <div style={statRow}>
              {stat(broken.total_targets, 'Broken URLs', 'var(--red,#c0392b)')}
              {stat(broken.linked_targets ?? 0, 'Linked from pages')}
              {stat(broken.total_links ?? 0, 'Broken link instances')}
            </div>
            <p style={{ fontSize: 12, color: 'var(--muted,#6b7280)', margin: '0 0 10px' }}>
              Each broken URL below lists exactly which page links to it, the anchor text, the section
              (nearest heading) and the zone — hand this to the dev/AEM team as-is.
            </p>
            {broken.targets.map((t) => (
              <details key={t.url} style={{ border: '1px solid var(--border,#e2e6ee)', borderRadius: 8, marginBottom: 8 }}>
                <summary style={{ padding: '8px 10px', cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  {badge(t.status, 'var(--red,#c0392b)')}
                  <code style={{ fontSize: 12 }}>{pathOf(t.url)}</code>
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
                          <td style={td}>{s.section || <em style={{ color: 'var(--muted,#9aa3b2)' }}>—</em>}</td>
                          <td style={td}>{s.zone && badge(s.zone, 'var(--muted,#6b7280)')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ))}
            {broken.orphan_broken && broken.orphan_broken.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted,#6b7280)' }}>
                  {broken.orphan_broken.length} broken URL(s) with no on-page link found (came via sitemap/redirect)
                </summary>
                <ul style={{ fontSize: 12, marginTop: 6 }}>
                  {broken.orphan_broken.map((o) => <li key={o.url}><code>{pathOf(o.url)}</code> {badge(o.status, 'var(--red,#c0392b)')}</li>)}
                </ul>
              </details>
            )}
          </>
        )}
      </section>

      {/* ── 2. Redirects ─────────────────────────────────────────────── */}
      <section style={card}>
        <h2 style={h2}><Icon name="alt_route" /> Redirects</h2>
        {!sec ? <Loading /> : (
          <>
            <div style={statRow}>
              {stat(sec.redirects.counts['301'], '301 Permanent')}
              {stat(sec.redirects.counts.other_3xx, 'Other 3xx', 'var(--amber,#d98e00)')}
              {stat(sec.redirects.counts.loops, 'Redirect loops', 'var(--red,#c0392b)')}
            </div>
            <SampleTable
              rows={sec.redirects.rows}
              cols={[
                ['From', (r) => <code>{pathOf(r.url)}</code>],
                ['Status', (r) => badge(r.status_code, r.loop ? 'var(--red,#c0392b)' : 'var(--amber,#d98e00)')],
                ['Hops', (r) => String(r.hops)],
                ['Final URL', (r) => r.final_url ? <code>{pathOf(r.final_url)}</code> : '—'],
              ]}
            />
          </>
        )}
      </section>

      {/* ── 3. Soft 404 ──────────────────────────────────────────────── */}
      <section style={card}>
        <h2 style={h2}><Icon name="report_problem" /> Soft 404s <small style={{ fontWeight: 400, color: 'var(--muted)' }}>(HTTP 200 but &lt;100 words)</small></h2>
        {!sec ? <Loading /> : sec.soft_404.count === 0 ? <Empty label="No soft-404 pages." /> : (
          <SampleTable
            rows={sec.soft_404.rows}
            cols={[['URL', (r) => <code>{pathOf(r.url)}</code>], ['Words', (r) => String(r.word_count)], ['Title', (r) => r.title || '—']]}
          />
        )}
      </section>

      {/* ── 4. Sitemap ───────────────────────────────────────────────── */}
      <section style={card}>
        <h2 style={h2}><Icon name="account_tree" /> Sitemap coverage</h2>
        {!sec ? <Loading /> : (
          <>
            <div style={statRow}>
              {stat(sec.sitemap.counts.in_sitemap, 'In sitemap')}
              {stat(sec.sitemap.counts.discovered_only, 'Discovered only', 'var(--muted,#6b7280)')}
              {stat(sec.sitemap.counts.sitemap_errors, 'Sitemap URLs erroring', 'var(--red,#c0392b)')}
            </div>
            <SampleTable rows={sec.sitemap.error_rows} cols={[['Sitemap URL that errors', (r) => <code>{pathOf(r.url)}</code>], ['Status', (r) => badge(r.status_code, 'var(--red,#c0392b)')]]} />
          </>
        )}
      </section>

      {/* ── 5. robots.txt ────────────────────────────────────────────── */}
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

      {/* ── 6. Top internal-linked pages (pagerank in-degree) ─────────── */}
      <section style={card}>
        <h2 style={h2}><Icon name="hub" /> Top pages by internal linking</h2>
        {!prank ? <Loading /> : (
          <>
            <div style={statRow}>
              {stat(prank.summary.node_count, 'Pages in graph')}
              {stat(prank.summary.edge_count, 'Internal links')}
              {stat(prank.summary.orphan_count, 'Orphans (0 inbound)', 'var(--amber,#d98e00)')}
            </div>
            <SampleTable
              rows={prank.top.slice(0, 30)}
              cols={[['Page', (r) => <code>{pathOf(r.url)}</code>], ['Inbound', (r) => String(r.in_degree)], ['Outbound', (r) => String(r.out_degree)], ['PR score', (r) => String(r.pagerank_score)]]}
            />
          </>
        )}
      </section>

      {/* ── 7. Internal / external linking ───────────────────────────── */}
      <section style={card}>
        <h2 style={h2}><Icon name="share" /> Internal &amp; external linking</h2>
        {!sec ? <Loading /> : (
          <>
            <div style={statRow}>
              {stat(sec.linking.total_internal.toLocaleString(), 'Internal links (on-page)')}
              {stat(sec.linking.total_external.toLocaleString(), 'External links')}
              {stat(sec.linking.pages_no_internal_links.length, 'Pages with 0 internal links', 'var(--amber,#d98e00)')}
            </div>
            <details><summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>Top pages by external links</summary>
              <SampleTable rows={sec.linking.top_external_pages} cols={[['Page', (r) => <code>{pathOf(r.url)}</code>], ['External', (r) => String(r.external_links_count)], ['Internal', (r) => String(r.internal_links_count)]]} />
            </details>
            {sec.linking.pages_no_internal_links.length > 0 && (
              <details><summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--muted)' }}>Pages with no internal links (dead-ends)</summary>
                <SampleTable rows={sec.linking.pages_no_internal_links} cols={[['Page', (r) => <code>{pathOf(r.url)}</code>], ['Title', (r) => r.title || '—']]} />
              </details>
            )}
          </>
        )}
      </section>

      {/* ── 7b. External links — the actual outbound URLs (clickable) ──── */}
      <section style={card}>
        <h2 style={h2}><Icon name="open_in_new" /> External links — where this site links out</h2>
        <p style={{ fontSize: 12, color: 'var(--muted,#6b7280)', margin: '0 0 12px' }}>
          Every outbound link to another website, grouped by destination domain. Expand a domain to see
          the exact URLs (click to open), and expand a URL to see which of your pages link to it.
        </p>
        {!extlinks ? (
          <Loading label="Collecting every outbound link across the crawl…" />
        ) : extlinks.total_domains === 0 ? (
          <Empty label="No external links found." />
        ) : (
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
                  <a href={`https://${dom.domain}`} target="_blank" rel="noreferrer noopener" style={{ marginLeft: 'auto', fontSize: 11 }}>visit ↗</a>
                </summary>
                <div style={{ padding: '2px 10px 10px' }}>
                  {dom.urls.map((u) => (
                    <details key={u.url} style={{ borderTop: '1px solid var(--border,#eef1f6)' }}>
                      <summary style={{ padding: '6px 4px', cursor: 'pointer', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <a href={u.url} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} style={{ wordBreak: 'break-all' }}>{u.url}</a>
                        <span style={{ fontSize: 11, color: 'var(--muted,#6b7280)' }}>· linked {u.count}×</span>
                      </summary>
                      <div style={{ padding: '2px 0 8px 14px' }}>
                        {u.anchors.length > 0 && (
                          <div style={{ fontSize: 11, color: 'var(--muted,#6b7280)', marginBottom: 4 }}>
                            anchors: {u.anchors.map((a) => `“${a}”`).join(', ')}
                          </div>
                        )}
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

      {/* ── 8. PDF health ────────────────────────────────────────────── */}
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
            <SampleTable
              rows={sec.pdf.rows}
              cols={[
                ['PDF', (r) => <code>{pathOf(r.url)}</code>],
                ['Status', (r) => r.has_error ? badge(r.reasons.join(', ') || 'error', 'var(--red,#c0392b)') : badge('ok', 'var(--green,#1f9d55)')],
                ['Pages', (r) => String(r.pages || '—')],
                ['Size', (r) => r.byte_size ? `${Math.round(r.byte_size / 1024)} KB` : '—'],
              ]}
            />
          </>
        )}
      </section>

      {/* ── 9. Backlinks ─────────────────────────────────────────────── */}
      <section style={card}>
        <h2 style={h2}><Icon name="input" /> Backlinks <small style={{ fontWeight: 400, color: 'var(--muted)' }}>(own-domain inbound)</small></h2>
        {!backlinks ? <Loading /> : backlinks.summary.total === 0 ? (
          <Empty label="No backlinks discovered yet — the own-domain backlink discovery pipeline hasn't been run/built. (Tracked in BACKLINKS_PLAN.md.)" />
        ) : (
          <>
            <div style={statRow}>{stat(backlinks.summary.total, 'Backlinks')}{stat(backlinks.summary.top_referring_domains.length, 'Referring domains')}</div>
            <SampleTable rows={backlinks.backlinks} cols={[['From', (r) => <code>{r.source_domain}</code>], ['To', (r) => <code>{pathOf(r.target_url)}</code>], ['Anchor', (r) => r.anchor_text || '—'], ['Rel', (r) => r.nofollow ? badge('nofollow', 'var(--muted)') : 'follow']]} />
          </>
        )}
      </section>
    </div>
  );
}

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
      <thead><tr>{cols.map(([h]) => <th key={h} style={th}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => <tr key={i}>{cols.map(([h, render]) => <td key={h} style={td}>{render(r)}</td>)}</tr>)}
      </tbody>
    </table>
  );
}
