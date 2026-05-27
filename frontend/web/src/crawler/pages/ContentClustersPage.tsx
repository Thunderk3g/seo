/**
 * ContentClustersPage — `/crawler/content-clusters`.
 *
 * Editor-facing companion to the 3D Content Map. Where the map shows
 * cluster *shape*, this page enumerates the corpus as a navigable tree:
 *
 *     Product (Term, ULIP, …)
 *       └── Page-type (Calculator, Product landing, Blog/Guide, …)
 *             └── individual pages (URL, title, confidence badge)
 *
 * Two modes:
 *   • Primary  — each page bucketed once (highest-confidence product)
 *   • Multi    — each page listed under every matching product
 *
 * Pure rule-based on the backend (no LLM, no embeddings needed) so this
 * works on day-1 of the in-house content phase. Once embeddings exist,
 * clicking any leaf will open the existing similarity panel.
 *
 * Brand: Bajaj navy/gold palette per project memory.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { crawlerApi } from '../api';
import ContentDendrogram from '../components/ContentDendrogram';

// Bajaj-friendly product palette, kept in sync with ContentMapPage.
const PRODUCT_COLOURS: Record<string, string> = {
  term:         '#003DA5',
  ulip:         '#8B5CF6',
  endowment:    '#0EA5E9',
  retirement:   '#10B981',
  child:        '#F59E0B',
  group:        '#EC4899',
  wellness:     '#14B8A6',
  tax:          '#EF4444',
  nri:          '#FDB913',
  general_life: '#64748B',
};

type Mode = 'primary' | 'multi';
type View = 'accordion' | 'dendrogram';

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  let bg = '#E5E7EB';
  let fg = '#374151';
  if (value >= 0.85)      { bg = '#DCFCE7'; fg = '#166534'; }
  else if (value >= 0.70) { bg = '#FEF9C3'; fg = '#854D0E'; }
  else if (value >= 0.60) { bg = '#FFEDD5'; fg = '#9A3412'; }
  return (
    <span style={{
      background: bg, color: fg, padding: '1px 6px', borderRadius: 4,
      fontSize: 11, fontWeight: 600,
    }}>
      {pct}%
    </span>
  );
}

function TierBadge({ tier }: { tier: number }) {
  const label = tier === 1 ? 'rules' : tier === 3 ? 'semantic' : `T${tier}`;
  return (
    <span style={{
      background: '#F3F4F6', color: '#6B7280', padding: '1px 6px',
      borderRadius: 4, fontSize: 11, fontFamily: 'ui-monospace, monospace',
    }}>
      {label}
    </span>
  );
}

export default function ContentClustersPage() {
  const [mode, setMode] = useState<Mode>('primary');
  const [view, setView] = useState<View>('accordion');
  const [expandedProducts, setExpandedProducts] = useState<Set<string>>(new Set());
  const [expandedPageTypes, setExpandedPageTypes] = useState<Set<string>>(new Set());
  const [showUncertain, setShowUncertain] = useState(false);
  const [snapshotId, setSnapshotId] = useState<string>('');

  // Snapshot picker — empty string = "latest", any other value = explicit
  // snapshot UUID. Lets the operator cluster competitor crawls the same
  // way they cluster Bajaj's.
  const snapshotsQ = useQuery({
    queryKey: ['crawler', 'snapshots-list'],
    queryFn: () => crawlerApi.snapshots(),
    staleTime: 60_000,
  });

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'content-clusters', mode, snapshotId],
    queryFn: () => crawlerApi.contentClusters({
      mode,
      ...(snapshotId ? { snapshot: snapshotId } : {}),
    }),
    staleTime: 5 * 60_000,
  });

  const toggleProduct = (key: string) => {
    setExpandedProducts((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const togglePageType = (key: string) => {
    setExpandedPageTypes((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const expandAll = () => {
    if (!data) return;
    setExpandedProducts(new Set(data.products.map((p) => p.product)));
    setExpandedPageTypes(new Set(
      data.products.flatMap((p) => p.page_types.map((pt) => `${p.product}:${pt.page_type}`)),
    ));
  };

  const collapseAll = () => {
    setExpandedProducts(new Set());
    setExpandedPageTypes(new Set());
  };

  if (isLoading) return <div style={{ padding: 24 }}>Loading clusters…</div>;
  if (isError) return (
    <div style={{ padding: 24, color: '#B91C1C' }}>
      Failed to load: {(error as Error)?.message || 'unknown'}
    </div>
  );
  if (!data) return null;

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ margin: 0, color: '#003DA5', fontSize: 24 }}>
          Content Clusters
        </h1>
        <p style={{ margin: '4px 0 0', color: '#6B7280', fontSize: 14 }}>
          {(() => {
            const sel = (snapshotsQ.data?.snapshots || []).find(
              (s) => s.id === data.snapshot_id,
            );
            const who =
              !sel || sel.kind === 'bajaj'
                ? 'Bajaj corpus'
                : `${sel.target_domain || 'competitor'} corpus`;
            return `${who} organised as Product → Page-type → pages.`;
          })()}{' '}
          Snapshot {data.snapshot_id.slice(0, 8)} ·{' '}
          {new Date(data.snapshot_date).toLocaleDateString()}
        </p>
      </div>

      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        padding: 12, marginBottom: 16, background: '#F9FAFB',
        border: '1px solid #E5E7EB', borderRadius: 8,
      }}>
        {/* Snapshot picker — drives competitor cluster parity. */}
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginRight: 8 }}>
            Snapshot
          </label>
          <select
            value={snapshotId}
            onChange={(e) => setSnapshotId(e.target.value)}
            style={{
              padding: '6px 10px', fontSize: 13, border: '1px solid #D1D5DB',
              borderRadius: 6, background: '#FFFFFF', cursor: 'pointer',
              minWidth: 240,
            }}
          >
            <option value="">Latest Bajaj (default)</option>
            {(snapshotsQ.data?.snapshots || []).map((s) => {
              const date = s.started_at ? new Date(s.started_at).toLocaleDateString() : '';
              const label =
                s.kind === 'bajaj'
                  ? `Bajaj · ${date} · ${s.ok_page_count}p`
                  : `${s.target_domain || 'competitor'} · ${date} · ${s.ok_page_count}p`;
              return (
                <option key={s.id} value={s.id}>{label}</option>
              );
            })}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginRight: 8 }}>
            View
          </label>
          <div style={{ display: 'inline-flex', borderRadius: 6, overflow: 'hidden', border: '1px solid #D1D5DB' }}>
            <button
              type="button"
              onClick={() => setMode('primary')}
              style={{
                padding: '6px 12px', fontSize: 13, border: 'none',
                background: mode === 'primary' ? '#003DA5' : '#FFFFFF',
                color: mode === 'primary' ? '#FFFFFF' : '#374151',
                cursor: 'pointer', fontWeight: 600,
              }}
            >
              Primary only
            </button>
            <button
              type="button"
              onClick={() => setMode('multi')}
              style={{
                padding: '6px 12px', fontSize: 13, border: 'none',
                background: mode === 'multi' ? '#003DA5' : '#FFFFFF',
                color: mode === 'multi' ? '#FFFFFF' : '#374151',
                cursor: 'pointer', fontWeight: 600,
                borderLeft: '1px solid #D1D5DB',
              }}
            >
              Multi-label
            </button>
          </div>
        </div>

        <div style={{ marginLeft: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginRight: 8 }}>
            Layout
          </label>
          <div style={{ display: 'inline-flex', borderRadius: 6, overflow: 'hidden', border: '1px solid #D1D5DB' }}>
            <button
              type="button"
              onClick={() => setView('accordion')}
              style={{
                padding: '6px 12px', fontSize: 13, border: 'none',
                background: view === 'accordion' ? '#003DA5' : '#FFFFFF',
                color: view === 'accordion' ? '#FFFFFF' : '#374151',
                cursor: 'pointer', fontWeight: 600,
              }}
            >
              Accordion
            </button>
            <button
              type="button"
              onClick={() => setView('dendrogram')}
              style={{
                padding: '6px 12px', fontSize: 13, border: 'none',
                background: view === 'dendrogram' ? '#003DA5' : '#FFFFFF',
                color: view === 'dendrogram' ? '#FFFFFF' : '#374151',
                cursor: 'pointer', fontWeight: 600,
                borderLeft: '1px solid #D1D5DB',
              }}
            >
              Dendrogram
            </button>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        {view === 'accordion' && (
          <>
            <button type="button" onClick={expandAll} style={btnGhostStyle}>Expand all</button>
            <button type="button" onClick={collapseAll} style={btnGhostStyle}>Collapse all</button>
          </>
        )}
      </div>

      {/* Totals */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
        <Stat label="Pages" value={data.totals.pages} />
        <Stat label="Classified" value={data.totals.classified} />
        <Stat
          label="Assignments"
          value={data.totals.assignments}
          hint={mode === 'multi' ? 'a page can sit in multiple buckets' : 'one per page'}
        />
        <Stat
          label="Uncertain"
          value={data.totals.uncertain}
          tone={data.totals.uncertain > 0 ? 'warn' : 'ok'}
        />
      </div>

      {/* Product tree */}
      {data.products.length === 0 && (
        <div style={{ padding: 24, color: '#6B7280', textAlign: 'center' }}>
          No products classified yet. Run the crawler and{' '}
          <code>python manage.py classify_content</code> first.
        </div>
      )}

      {view === 'dendrogram' && data.products.length > 0 && (
        <ContentDendrogram
          products={data.products}
          rootLabel={`Bajaj content · ${data.totals.classified} pages`}
        />
      )}

      {view === 'accordion' && data.products.map((prod) => {
        const isOpen = expandedProducts.has(prod.product);
        const colour = PRODUCT_COLOURS[prod.product] || '#64748B';
        return (
          <div key={prod.product} style={{
            marginBottom: 8, border: '1px solid #E5E7EB', borderRadius: 8,
            overflow: 'hidden', background: '#FFFFFF',
          }}>
            <button
              type="button"
              onClick={() => toggleProduct(prod.product)}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                padding: '12px 16px', background: '#FFFFFF', border: 'none',
                cursor: 'pointer', textAlign: 'left',
                borderLeft: `4px solid ${colour}`,
              }}
            >
              <span style={{ fontSize: 14, color: '#6B7280', width: 14 }}>
                {isOpen ? '▾' : '▸'}
              </span>
              <span style={{ fontSize: 16, fontWeight: 600, color: '#111827' }}>
                {prod.label}
              </span>
              <span style={{
                background: colour, color: '#FFFFFF', padding: '2px 8px',
                borderRadius: 999, fontSize: 12, fontWeight: 600,
              }}>
                {prod.count}
              </span>
              <span style={{ fontSize: 12, color: '#6B7280' }}>
                across {prod.page_types.length} page type{prod.page_types.length === 1 ? '' : 's'}
              </span>
            </button>

            {isOpen && (
              <div style={{ background: '#F9FAFB', borderTop: '1px solid #E5E7EB' }}>
                {prod.page_types.map((pt) => {
                  const key = `${prod.product}:${pt.page_type}`;
                  const ptOpen = expandedPageTypes.has(key);
                  return (
                    <div key={key} style={{ borderBottom: '1px solid #E5E7EB' }}>
                      <button
                        type="button"
                        onClick={() => togglePageType(key)}
                        style={{
                          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                          padding: '8px 16px 8px 36px', background: 'transparent',
                          border: 'none', cursor: 'pointer', textAlign: 'left',
                        }}
                      >
                        <span style={{ fontSize: 13, color: '#6B7280', width: 12 }}>
                          {ptOpen ? '▾' : '▸'}
                        </span>
                        <span style={{ fontSize: 14, color: '#374151', fontWeight: 500 }}>
                          {pt.label}
                        </span>
                        <span style={{
                          background: '#E5E7EB', color: '#374151', padding: '1px 8px',
                          borderRadius: 999, fontSize: 11, fontWeight: 600,
                        }}>
                          {pt.count}
                        </span>
                      </button>

                      {ptOpen && (
                        <ul style={{
                          margin: 0, padding: '4px 16px 12px 60px',
                          listStyle: 'none',
                        }}>
                          {pt.pages.map((page) => (
                            <li key={page.url} style={{
                              display: 'flex', alignItems: 'center', gap: 10,
                              padding: '6px 0', fontSize: 13,
                            }}>
                              <a href={page.url} target="_blank" rel="noreferrer"
                                 style={{ color: '#003DA5', textDecoration: 'none', flex: 1, minWidth: 0 }}>
                                <div style={{
                                  overflow: 'hidden', textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap', fontWeight: 500,
                                }}>
                                  {page.title || '(untitled)'}
                                </div>
                                <div style={{
                                  overflow: 'hidden', textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap', color: '#6B7280', fontSize: 11,
                                }}>
                                  {page.url}
                                </div>
                              </a>
                              <ConfidenceBadge value={page.confidence} />
                              <TierBadge tier={page.tier} />
                              {mode === 'multi' && page.products.length > 1 && (
                                <span style={{
                                  fontSize: 10, color: '#6B7280',
                                  border: '1px dashed #D1D5DB', padding: '1px 6px',
                                  borderRadius: 4,
                                }}>
                                  also: {page.products.filter((p) => p !== prod.product).join(', ')}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {/* Uncertain bucket */}
      {data.uncertain.count > 0 && (
        <div style={{
          marginTop: 24, border: '1px solid #FCD34D', borderRadius: 8,
          background: '#FFFBEB', overflow: 'hidden',
        }}>
          <button
            type="button"
            onClick={() => setShowUncertain(!showUncertain)}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 16px', background: 'transparent', border: 'none',
              cursor: 'pointer', textAlign: 'left',
            }}
          >
            <span style={{ fontSize: 14, color: '#92400E', width: 14 }}>
              {showUncertain ? '▾' : '▸'}
            </span>
            <span style={{ fontSize: 15, fontWeight: 600, color: '#92400E' }}>
              Uncertain
            </span>
            <span style={{
              background: '#F59E0B', color: '#FFFFFF', padding: '2px 8px',
              borderRadius: 999, fontSize: 12, fontWeight: 600,
            }}>
              {data.uncertain.count}
            </span>
            <span style={{ fontSize: 12, color: '#92400E' }}>
              Tier-1 rules couldn't pin these down. Run Tier 3 (MiniLM) or refine seeds.
            </span>
          </button>
          {showUncertain && (
            <ul style={{ margin: 0, padding: '4px 16px 12px 36px', listStyle: 'none' }}>
              {data.uncertain.pages.map((page) => (
                <li key={page.url} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '4px 0', fontSize: 13,
                }}>
                  <a href={page.url} target="_blank" rel="noreferrer"
                     style={{ color: '#92400E', textDecoration: 'none', flex: 1, minWidth: 0 }}>
                    <div style={{
                      overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap', fontWeight: 500,
                    }}>
                      {page.title || '(untitled)'}
                    </div>
                    <div style={{
                      overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap', color: '#A16207', fontSize: 11,
                    }}>
                      {page.url}
                    </div>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const btnGhostStyle: React.CSSProperties = {
  padding: '6px 10px', fontSize: 12, fontWeight: 600,
  background: '#FFFFFF', color: '#374151',
  border: '1px solid #D1D5DB', borderRadius: 6, cursor: 'pointer',
};

function Stat({ label, value, hint, tone = 'neutral' }: {
  label: string; value: number; hint?: string;
  tone?: 'neutral' | 'ok' | 'warn';
}) {
  const colour = tone === 'warn' ? '#B45309' : tone === 'ok' ? '#15803D' : '#003DA5';
  return (
    <div style={{
      flex: 1, padding: 12, background: '#FFFFFF',
      border: '1px solid #E5E7EB', borderRadius: 8,
    }}>
      <div style={{ fontSize: 11, color: '#6B7280', textTransform: 'uppercase', fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: colour, marginTop: 4 }}>
        {value.toLocaleString()}
      </div>
      {hint && (
        <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>{hint}</div>
      )}
    </div>
  );
}
