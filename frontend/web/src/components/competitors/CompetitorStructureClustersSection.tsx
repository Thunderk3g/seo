import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';

const BAJAJ_BLUE = '#0072ce';
const BAJAJ_NAVY = '#002c6e';

interface ClusterSection {
  level: number;
  tag: string;
  heading: string;
}

interface ClusterPage {
  key: string;
  name: string;
  url: string;
  words: number;
  h1?: number;
  h2?: number;
  h3?: number;
  links_internal?: number | null;
  links_external?: number | null;
  images?: number | null;
  sections: ClusterSection[];
}

interface Cluster {
  id: string;
  name: string;
  intro: string;
  page_count: number;
  section_count: number;
  word_count: number;
  pages: ClusterPage[];
}

interface HierarchyNode {
  segment: string;
  pages: number;
  children: { segment: string; pages: number }[];
}

interface StructureClustersResponse {
  available: boolean;
  domain?: string;
  error?: string;
  snapshot?: { id: string; started_at: string; status: string };
  summary?: {
    pages_crawled: number;
    pages_200: number;
    h1_total: number;
    h2_total: number;
    h3_total: number;
    internal_links_total: number | null;
    external_links_total: number | null;
  };
  hierarchy?: HierarchyNode[];
  cluster_source?: string;
  note?: string;
  clusters?: Cluster[];
}

function Chip({ n, label }: { n: number | string; label: string }) {
  return (
    <div style={{ flex: '0 1 130px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '8px 10px' }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: BAJAJ_BLUE }}>{n}</div>
      <div style={{ fontSize: 11, color: '#475569' }}>{label}</div>
    </div>
  );
}

function b64url(s: string): string {
  return btoa(unescape(encodeURIComponent(s)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function MiniStat({ label, value }: { label: string; value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <span style={{ fontSize: 11, color: '#475569', background: '#f1f5f9', borderRadius: 6, padding: '0 6px', marginRight: 6, whiteSpace: 'nowrap' }}>
      {label} <b style={{ color: BAJAJ_NAVY }}>{value.toLocaleString()}</b>
    </span>
  );
}

function ClusterBlock({ cluster, snapshotId }: { cluster: Cluster; snapshotId?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: '1px solid #e2e8f0', borderLeft: `4px solid ${BAJAJ_BLUE}`, borderRadius: 8, margin: '8px 0', background: '#fbfdff' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 12px', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}
      >
        <span style={{ width: 12, color: BAJAJ_BLUE, fontWeight: 700 }}>{open ? '▾' : '▸'}</span>
        <span style={{ fontWeight: 700, color: BAJAJ_NAVY, fontSize: 14 }}>{cluster.name}</span>
        <span style={{ fontSize: 11.5, fontWeight: 700, background: '#dbeafe', color: '#1e40af', borderRadius: 999, padding: '1px 9px' }}>
          {cluster.page_count} pages · {cluster.word_count.toLocaleString()} words
        </span>
      </button>
      {open && (
        <div style={{ padding: '0 12px 10px 32px' }}>
          {cluster.intro && <div style={{ fontSize: 12.5, color: '#475569', marginBottom: 6 }}>{cluster.intro}</div>}
          {cluster.pages.map((p) => (
            <div key={p.key} style={{ margin: '8px 0', fontSize: 12.5 }}>
              <a href={p.url} target="_blank" rel="noreferrer" style={{ color: '#1e40af', fontWeight: 600, textDecoration: 'none' }}>
                {p.name}
              </a>
              <div style={{ margin: '3px 0' }}>
                <MiniStat label="Words" value={p.words} />
                <MiniStat label="H1" value={p.h1} />
                <MiniStat label="H2" value={p.h2} />
                <MiniStat label="H3" value={p.h3} />
                <MiniStat label="Int. links" value={p.links_internal} />
                <MiniStat label="Ext. links" value={p.links_external} />
                <MiniStat label="Images" value={p.images} />
                {snapshotId && (
                  <a
                    href={`/crawler/pages/${snapshotId}/${b64url(p.url)}`}
                    style={{ fontSize: 11.5, fontWeight: 700, color: '#1e40af', textDecoration: 'none' }}
                  >
                    Full page report →
                  </a>
                )}
              </div>
              {p.sections.length > 0 && (
                <div style={{ color: '#475569', marginTop: 2 }}>
                  {p.sections.slice(0, 6).map((s, i) => (
                    <span key={`${p.key}-s${i}`} style={{ marginRight: 10 }}>
                      <b style={{ color: '#94a3b8' }}>{s.tag}</b> {s.heading}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Content segregation by the COMPETITOR'S OWN page structure — their URL
 * sections by default, or the per-domain spec the Claude smart-clustering
 * pass writes after a crawl. Live: populates while a crawl is running.
 * No CWV here by design (competitor CWV is single-page-crawl only).
 */
export default function CompetitorStructureClustersSection({ domain }: { domain: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['competitor-structure-clusters', domain],
    queryFn: () =>
      api.get<StructureClustersResponse>(`/seo/competitors/${encodeURIComponent(domain)}/content-clusters/`),
    staleTime: 60_000,
  });

  // Page search — client-side filter over the fetched payload only
  // (no extra API calls; the crawler is untouched).
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const visibleClusters = useMemo(() => {
    const clusters = data?.clusters ?? [];
    if (!q) return clusters;
    return clusters
      .map((c) => {
        const pages = c.pages.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            p.url.toLowerCase().includes(q) ||
            p.sections.some((s) => (s.heading || '').toLowerCase().includes(q))
        );
        return { ...c, pages, page_count: pages.length, word_count: pages.reduce((n, p) => n + p.words, 0) };
      })
      .filter((c) => c.pages.length > 0);
  }, [data, q]);
  const matchCount = q ? visibleClusters.reduce((n, c) => n + c.pages.length, 0) : 0;

  if (isLoading) return <div className="seo-empty">Loading content segregation…</div>;
  if (!data?.available) {
    return (
      <section style={{ marginTop: 22 }}>
        <h2 style={{ fontSize: 18, color: BAJAJ_BLUE }}>Content segregation</h2>
        <div className="seo-empty">{data?.error || 'No crawl data yet for this competitor.'}</div>
      </section>
    );
  }
  const s = data.summary;
  return (
    <section style={{ marginTop: 22 }}>
      <h2 style={{ fontSize: 18, color: BAJAJ_BLUE, borderBottom: '1px solid #cbd5e1', paddingBottom: 4 }}>
        Content segregation — their page structure
      </h2>
      {data.note && <div style={{ fontSize: 12, color: '#64748b', margin: '4px 0 10px' }}>{data.note}</div>}
      {s && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
          <Chip n={s.pages_crawled.toLocaleString()} label="Pages crawled" />
          <Chip n={s.pages_200.toLocaleString()} label="HTTP 200" />
          <Chip n={s.h1_total.toLocaleString()} label="H1 tags" />
          <Chip n={s.h2_total.toLocaleString()} label="H2 tags" />
          <Chip n={s.h3_total.toLocaleString()} label="H3 tags" />
          {s.internal_links_total !== null && (
            <Chip n={s.internal_links_total.toLocaleString()} label="Internal links" />
          )}
          {s.external_links_total !== null && (
            <Chip n={s.external_links_total.toLocaleString()} label="External links" />
          )}
        </div>
      )}
      {data.hierarchy && data.hierarchy.length > 0 && (
        <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 14px', fontSize: 12.5, marginBottom: 10 }}>
          <b style={{ color: BAJAJ_NAVY }}>Page hierarchy:</b>{' '}
          {data.hierarchy.map((h) => (
            <span key={h.segment} style={{ marginRight: 14 }}>
              <code>/{h.segment}</code> ({h.pages})
              {h.children.length > 0 && (
                <span style={{ color: '#64748b' }}>
                  {' '}→ {h.children.slice(0, 4).map((c) => `${c.segment} (${c.pages})`).join(', ')}
                </span>
              )}
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 10px' }}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search their pages — title, URL or heading…"
          style={{
            flex: '1 1 300px',
            maxWidth: 460,
            padding: '8px 12px',
            border: '1px solid #cbd5e1',
            borderRadius: 8,
            fontSize: 13,
          }}
        />
        {q && (
          <span style={{ fontSize: 12.5, color: '#475569' }}>
            {matchCount.toLocaleString()} page(s) match
          </span>
        )}
      </div>
      {visibleClusters.map((c) => (
        <ClusterBlock key={c.id} cluster={c} snapshotId={data.snapshot?.id} />
      ))}
      {q && visibleClusters.length === 0 && (
        <div className="seo-empty">No crawled page matches “{query}”.</div>
      )}
    </section>
  );
}
