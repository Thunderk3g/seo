import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import {
  useContentClusters,
  type ContentCluster,
  type ContentPageBlock,
} from '../api/hooks/useContentClusters';
import { useIndexReconciliation } from '../api/hooks/useIndexReconciliation';

const BAJAJ_BLUE = '#0072ce';
const BAJAJ_NAVY = '#002c6e';

function Stat({ n, label, tone }: { n: number; label: string; tone?: string }) {
  return (
    <div style={{ flex: '1 1 110px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 12px' }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone || BAJAJ_BLUE }}>{n.toLocaleString()}</div>
      <div style={{ fontSize: 11.5, color: '#475569' }}>{label}</div>
    </div>
  );
}

function IndexCoveragePanel() {
  const { data, isLoading } = useIndexReconciliation();
  if (isLoading) return <div className="seo-empty">Loading index coverage…</div>;
  if (!data?.available || !data.reconciliation || !data.main_site) return null;
  const r = data.reconciliation;
  const subs = data.by_subdomain || {};
  return (
    <section style={{ margin: '14px 0 6px' }}>
      <h2 style={{ fontSize: 18, color: BAJAJ_BLUE, borderBottom: `1px solid #cbd5e1`, paddingBottom: 4 }}>
        Index coverage — GSC vs crawler
      </h2>
      <div style={{ fontSize: 12.5, color: '#475569', margin: '4px 0 10px' }}>
        Main site (<code>www</code>) from the latest crawl ({data.snapshot?.total_pages.toLocaleString()} pages total),
        vs GSC pages receiving impressions. {data.gsc?.note}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <Stat n={r.gsc_served_proxy} label="GSC pages w/ impressions" tone={BAJAJ_NAVY} />
        <Stat n={r.crawler_main_total} label="Crawler www pages" />
        <Stat n={r.crawler_main_indexable} label="Indexable" tone="#16a34a" />
        <Stat n={r.crawler_main_noindex} label="noindex" tone="#b45309" />
        <Stat n={r.crawler_main_canonicalized} label="Canonicalized" tone="#b45309" />
        <Stat n={r.crawler_main_404} label="404" tone="#b91c1b" />
        <Stat n={r.crawler_main_error} label="Errors/timeouts" tone="#b91c1b" />
      </div>
      <div style={{ marginTop: 10, fontSize: 12.5 }}>
        <b style={{ color: BAJAJ_NAVY }}>By subdomain:</b>{' '}
        {Object.entries(subs).map(([sd, b]) => (
          <span key={sd} style={{ marginRight: 14 }}>
            <code>{sd}</code>: {b.total.toLocaleString()} ({b.indexable} indexable, {b.status_404} 404)
          </span>
        ))}
      </div>
    </section>
  );
}

function fmt(n: number): string {
  return n.toLocaleString();
}

interface ContentCrawlSnapshot {
  snapshot_id: string;
  status: 'running' | 'complete' | 'failed' | 'stopped';
  started_at: string;
  finished_at: string;
  target_domain: string;
  pages_attempted: number;
  pages_ok: number;
}

interface ContentCrawlStatus {
  available: boolean;
  latest: ContentCrawlSnapshot | null;
}

/** Trigger + status for the own-site content crawl (sitemap-seeded walk
 *  that stores body text + zoned structure per page; the clusters below
 *  re-fill from it when it finishes). */
function ContentCrawlButton() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['content-crawl-status'],
    queryFn: () => api.get<ContentCrawlStatus>('/seo/content/crawl/'),
    // Poll only while a crawl is in flight; otherwise check on focus.
    refetchInterval: (query) =>
      query.state.data?.latest?.status === 'running' ? 10_000 : false,
  });
  const start = useMutation({
    mutationFn: () => api.post('/seo/content/crawl/'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['content-crawl-status'] }),
  });
  const latest = data?.latest ?? null;
  const running = latest?.status === 'running';
  // A finished crawl means fresher clusters — drop the cache ONCE per
  // run (keyed by snapshot id, not on every render).
  const doneKey = latest && latest.status === 'complete' ? latest.snapshot_id : '';
  useEffect(() => {
    if (doneKey) qc.invalidateQueries({ queryKey: ['content-clusters'] });
  }, [doneKey, qc]);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={running || start.isPending}
        style={{
          background: running ? '#94a3b8' : BAJAJ_BLUE,
          color: '#fff',
          border: 'none',
          borderRadius: 8,
          padding: '8px 16px',
          fontWeight: 700,
          fontSize: 13,
          cursor: running ? 'default' : 'pointer',
        }}
      >
        {running ? 'Content crawl running…' : 'Crawl site content'}
      </button>
      {latest && (
        <span style={{ fontSize: 12, color: '#475569' }}>
          {running
            ? `${fmt(latest.pages_ok)} pages captured so far`
            : `Last crawl: ${latest.status} · ${fmt(latest.pages_ok)} pages` +
              (latest.finished_at ? ` · ${new Date(latest.finished_at).toLocaleString()}` : '')}
        </span>
      )}
      {start.isError && (
        <span style={{ fontSize: 12, color: '#b91c1b' }}>
          Could not start — is a crawl already running?
        </span>
      )}
    </div>
  );
}

/** URL-safe base64 of a page URL — matches Django's urlsafe_b64 route
 *  param on /crawler/pages/<snapshotId>/<b64>. */
function b64url(s: string): string {
  return btoa(unescape(encodeURIComponent(s)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function StatChip({ label, value }: { label: string; value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <span style={{ fontSize: 11, color: '#475569', background: '#f1f5f9', borderRadius: 6, padding: '1px 7px', whiteSpace: 'nowrap' }}>
      {label} <b style={{ color: BAJAJ_NAVY }}>{value.toLocaleString()}</b>
    </span>
  );
}

function PageBlock({
  page,
  clusterId,
  snapshotId,
}: {
  page: ContentPageBlock;
  clusterId: string;
  snapshotId?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      style={{
        border: '1px solid #e2e8f0',
        borderLeft: `4px solid ${BAJAJ_BLUE}`,
        borderRadius: 8,
        margin: '8px 0',
        background: '#fbfdff',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
          padding: '8px 12px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <span style={{ width: 12, color: BAJAJ_BLUE, fontWeight: 700 }}>
          {open ? '▾' : '▸'}
        </span>
        <span style={{ fontWeight: 700, color: BAJAJ_NAVY, fontSize: 14 }}>{page.name}</span>
        <span style={{ fontSize: 12, color: '#64748b' }}>
          {page.sections.length} sections · {fmt(page.words)} words
        </span>
        <a
          href={page.url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          style={{ marginLeft: 'auto', fontSize: 11, fontFamily: 'monospace', color: '#94a3b8' }}
        >
          {page.url.replace('https://www.bajajlifeinsurance.com', '')}
        </a>
      </button>
      {open && (
        <div style={{ borderTop: '1px solid #eef2ff', padding: '6px 14px 12px' }}>
          {/* Per-page structure report — counts from the stored crawl
              row, plus the deep link to the full unified page report
              (all links, images, schema, body). */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '6px 0 4px' }}>
            <StatChip label="H1" value={page.h1} />
            <StatChip label="H2" value={page.h2} />
            <StatChip label="H3" value={page.h3} />
            <StatChip label="Internal links" value={page.links_internal} />
            <StatChip label="External links" value={page.links_external} />
            <StatChip label="Images" value={page.images} />
            <StatChip label="Words" value={page.words} />
            {snapshotId && (
              <a
                href={`/crawler/pages/${snapshotId}/${b64url(page.url)}`}
                style={{ fontSize: 11.5, fontWeight: 700, color: '#1e40af', textDecoration: 'none', padding: '1px 4px' }}
              >
                Full page report →
              </a>
            )}
          </div>
          {page.sections.map((s, i) => (
            <div
              key={`${clusterId}-${page.key}-${i}`}
              style={{
                margin: '8px 0',
                borderLeft: '2px solid #e2e8f0',
                paddingLeft: 10,
                marginLeft: s.level >= 3 ? 30 : s.level === 2 ? 14 : 0,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  style={{
                    minWidth: 26,
                    fontFamily: 'monospace',
                    fontSize: 10,
                    fontWeight: 700,
                    color: '#fff',
                    background: BAJAJ_NAVY,
                    borderRadius: 4,
                    padding: '1px 5px',
                    textAlign: 'center',
                  }}
                >
                  {s.tag}
                </span>
                <span style={{ fontWeight: 700, color: '#0f172a', fontSize: s.level === 1 ? 16 : 14 }}>
                  {s.heading || '(untitled)'}
                </span>
                <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>{s.words}w</span>
              </div>
              {s.text && (
                <div
                  style={{
                    color: '#334155',
                    margin: '3px 0 0',
                    whiteSpace: 'pre-wrap',
                    fontSize: 12.5,
                  }}
                >
                  {s.text}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ClusterSection({ cluster, snapshotId }: { cluster: ContentCluster; snapshotId?: string }) {
  return (
    <section style={{ marginTop: 28 }}>
      <h2
        id={cluster.id}
        style={{
          fontSize: 19,
          color: BAJAJ_BLUE,
          borderBottom: `2px solid ${BAJAJ_BLUE}`,
          paddingBottom: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
        }}
      >
        {cluster.name}
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            background: '#dbeafe',
            color: '#1e40af',
            borderRadius: 999,
            padding: '2px 10px',
          }}
        >
          {cluster.page_count} pages · {cluster.section_count} sections · {fmt(cluster.word_count)} words
        </span>
      </h2>
      {cluster.intro && (
        <div style={{ fontSize: 13, color: '#475569', margin: '6px 0 10px' }}>{cluster.intro}</div>
      )}
      {cluster.pages.map((p) => (
        <PageBlock key={`${cluster.id}-${p.key}`} page={p} clusterId={cluster.id} snapshotId={snapshotId} />
      ))}
    </section>
  );
}

export default function ContentPage() {
  const { data, isLoading, isError } = useContentClusters();
  const clusters = data?.clusters ?? [];

  // Page search — pure client-side filter over the already-fetched
  // cluster payload (no extra API calls, zero impact on the crawler).
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const visibleClusters = useMemo(() => {
    if (!q) return clusters;
    return clusters
      .map((c) => {
        const pages = c.pages.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            p.url.toLowerCase().includes(q) ||
            p.sections.some((s) => (s.heading || '').toLowerCase().includes(q))
        );
        return {
          ...c,
          pages,
          page_count: pages.length,
          section_count: pages.reduce((n, p) => n + p.sections.length, 0),
          word_count: pages.reduce((n, p) => n + p.words, 0),
        };
      })
      .filter((c) => c.pages.length > 0);
  }, [clusters, q]);
  const matchCount = q
    ? visibleClusters.reduce((n, c) => n + c.pages.length, 0)
    : 0;

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Content</h1>
          <div className="seo-page-sub">
            Every page&apos;s content segregated by topic across the whole site — term, ULIP, tax and
            more, pulled from wherever it appears. Click a page to read its real sections.
          </div>
        </div>
        <ContentCrawlButton />
      </header>

      {isLoading && <div className="seo-empty">Loading content clusters…</div>}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server is running on /api/v1/seo/.
        </div>
      )}
      {data && !data.available && (
        <div className="seo-empty">
          In-house content not built yet. Run a crawl so the crawler stores page content, then this
          page fills in automatically.
        </div>
      )}

      <IndexCoveragePanel />

      {clusters.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0 0' }}>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search pages — title, URL or heading (e.g. term calculator)…"
              style={{
                flex: '1 1 320px',
                maxWidth: 480,
                padding: '8px 12px',
                border: '1px solid #cbd5e1',
                borderRadius: 8,
                fontSize: 13,
              }}
            />
            {q && (
              <span style={{ fontSize: 12.5, color: '#475569' }}>
                {matchCount.toLocaleString()} page(s) match in {visibleClusters.length} topic(s)
              </span>
            )}
          </div>
          <div
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              fontSize: 13,
              margin: '12px 0',
            }}
          >
            <b style={{ color: BAJAJ_NAVY }}>Topics:</b>{' '}
            {visibleClusters.map((c) => (
              <a
                key={c.id}
                href={`#${c.id}`}
                style={{ color: '#1e40af', marginRight: 14, textDecoration: 'none' }}
              >
                {c.name}{q ? ` (${c.pages.length})` : ''}
              </a>
            ))}
          </div>
          {visibleClusters.map((c) => (
            <ClusterSection key={c.id} cluster={c} snapshotId={data?.snapshot_id} />
          ))}
          {q && visibleClusters.length === 0 && (
            <div className="seo-empty">No crawled page matches “{query}”.</div>
          )}
        </>
      )}
    </div>
  );
}
