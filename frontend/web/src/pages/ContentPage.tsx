import { useState } from 'react';
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

function PageBlock({ page, clusterId }: { page: ContentPageBlock; clusterId: string }) {
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

function ClusterSection({ cluster }: { cluster: ContentCluster }) {
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
        <PageBlock key={`${cluster.id}-${p.key}`} page={p} clusterId={cluster.id} />
      ))}
    </section>
  );
}

export default function ContentPage() {
  const { data, isLoading, isError } = useContentClusters();
  const clusters = data?.clusters ?? [];

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
            {clusters.map((c) => (
              <a
                key={c.id}
                href={`#${c.id}`}
                style={{ color: '#1e40af', marginRight: 14, textDecoration: 'none' }}
              >
                {c.name}
              </a>
            ))}
          </div>
          {clusters.map((c) => (
            <ClusterSection key={c.id} cluster={c} />
          ))}
        </>
      )}
    </div>
  );
}
