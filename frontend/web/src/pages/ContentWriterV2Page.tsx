/**
 * ContentWriterV2Page — `/content-writer-v2`.
 *
 * SERP-discovery-driven page revamp. Distinct from the legacy
 * `/content-writer` flow:
 *   • Legacy compares us against a fixed DB roster of competitor brands.
 *   • V2 discovers competitors live from Google's top-10 SERP for the
 *     intent of the URL we want to revamp (the actual question users
 *     type to land on a page like ours).
 *
 * Stages rendered as separate panels so the operator can audit every
 * step the agent took:
 *   1. SERP discovery — synthesised query + top organic results +
 *      blocked aggregators + PAA / featured snippet / AI overview.
 *   2. Comparative structural analyzer — side-by-side numbers across
 *      ours + every competitor.
 *   3. Gap report — multi-dimensional deficits sorted by priority.
 *   4. SEO best-practices overlay — deterministic checklist with
 *      severity counts.
 *   5. Revamp draft — title, meta, H1, outline, body HTML preview +
 *      raw, FAQ list, internal-link plan, JSON-LD blocks, tech
 *      recommendations.
 *   6. Recent runs rail — re-open any past run without re-spending.
 */
import { useEffect, useMemo, useState } from 'react';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import {
  useCWV2Run,
  useCWV2Runs,
  useCWV2Start,
  type CWV2ClusterSection,
  type CWV2DimensionGap,
  type CWV2GapReport,
  type CWV2HeadingNode,
  type CWV2PageAnalysis,
  type CWV2PageStructure,
  type CWV2Revamp,
  type CWV2RunPayload,
  type CWV2SeoOverlay,
  type CWV2SerpStage,
} from '../api/hooks/useContentWriter';
import {
  downloadDoc,
  downloadHtml,
  downloadMarkdown,
  exportPdf,
} from '../lib/revampExport';

const EXPECTED_DURATION_S = 60;

function fmtUSD(n: number | undefined | null): string {
  return n == null ? '—' : `$${Number(n).toFixed(4)}`;
}

function fmtNum(n: number | undefined | null): string {
  return n == null ? '—' : Number(n).toLocaleString('en-IN');
}

function severityColor(s: string): string {
  if (s === 'critical') return '#b91c1c';
  if (s === 'warning') return '#b45309';
  return '#475569';
}

function priorityLabel(p: number): { label: string; color: string } {
  if (p === 3) return { label: 'P3 critical', color: '#b91c1c' };
  if (p === 2) return { label: 'P2 high', color: '#b45309' };
  if (p === 1) return { label: 'P1 medium', color: '#1d4ed8' };
  return { label: 'info', color: '#64748b' };
}

export default function ContentWriterV2Page() {
  const start = useCWV2Start();
  const runs = useCWV2Runs();

  const [urlInput, setUrlInput] = useState('');
  const [promptInput, setPromptInput] = useState('');
  const [maxComps, setMaxComps] = useState(5);
  const [customUrlsInput, setCustomUrlsInput] = useState('');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!start.isPending) {
      setElapsed(0);
      return;
    }
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [start.isPending]);

  const liveRun = start.data?.run_id ?? null;
  const storedRun = useCWV2Run(
    activeRunId && activeRunId !== liveRun ? activeRunId : null,
  );

  const payload: CWV2RunPayload | undefined =
    activeRunId === liveRun ? start.data : storedRun.data;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;
    const custom = customUrlsInput
      .split('\n')
      .map((u) => u.trim())
      .filter(Boolean);
    start.mutate(
      {
        our_url: urlInput.trim(),
        operator_prompt: promptInput.trim() || undefined,
        max_competitors: maxComps,
        custom_urls: custom.length ? custom : undefined,
      },
      {
        onSuccess: (data) => setActiveRunId(data.run_id),
      },
    );
  };

  const progress = Math.min(elapsed / EXPECTED_DURATION_S, 0.95);

  return (
    <div style={{ padding: 24, maxWidth: 1280, margin: '0 auto' }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 24, color: '#0f172a' }}>
          Content Writer v2 — SERP-Driven Page Revamp
        </h1>
        <p style={{ margin: '6px 0 0', color: '#475569', fontSize: 14 }}>
          Paste a Bajaj Life Insurance URL. We synthesize the search query
          Google would surface this page for, fetch the top 10 ranking
          competitor pages, deep-crawl + cluster + benchmark each one,
          then ask the writer to close every priority gap.
        </p>
      </header>

      {payload?.llm_enabled === false && (
        <div
          style={{
            marginBottom: 16,
            padding: '10px 14px',
            borderRadius: 6,
            background: '#fef3c7',
            border: '1px solid #f59e0b',
            color: '#92400e',
            fontSize: 13,
          }}
        >
          <strong>Content Writer LLM is disabled.</strong> The Anthropic key
          has been turned off, so new generation is paused — saved runs below
          remain fully viewable and downloadable. Re-enable the key in{' '}
          <code>.env</code> to resume new revamps.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Revamp a page</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={onSubmit}
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
          >
            <Input
              placeholder="https://www.bajajlifeinsurance.com/term-insurance-plans/..."
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
            />
            <Input
              placeholder="Optional steer — e.g. 'focus on tax benefits' or 'compare with HDFC only'"
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
            />
            <textarea
              placeholder={
                'Optional: paste exact competitor URLs to compare against (one per line).\n' +
                'These are always crawled. Tip: match the page type — for a product page, paste competitor product pages.\n' +
                'e.g. https://www.sbilife.co.in/ulip-plans'
              }
              value={customUrlsInput}
              onChange={(e) => setCustomUrlsInput(e.target.value)}
              rows={3}
              style={{
                width: '100%',
                padding: 8,
                border: '1px solid #cbd5e1',
                borderRadius: 4,
                fontSize: 13,
                fontFamily: 'inherit',
                resize: 'vertical',
              }}
            />
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 16 }}
            >
              <label style={{ color: '#475569', fontSize: 13 }}>
                Max competitors:&nbsp;
                <select
                  value={maxComps}
                  onChange={(e) => setMaxComps(Number(e.target.value))}
                  style={{
                    padding: '4px 8px',
                    border: '1px solid #cbd5e1',
                    borderRadius: 4,
                  }}
                >
                  {[3, 4, 5, 6, 7, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" disabled={start.isPending || !urlInput.trim()}>
                {start.isPending
                  ? `Running… (${elapsed}s)`
                  : 'Run SERP revamp'}
              </Button>
              {start.isPending && (
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div
                    style={{
                      height: 6,
                      background: '#e2e8f0',
                      borderRadius: 3,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${progress * 100}%`,
                        height: '100%',
                        background: '#1e40af',
                        transition: 'width 0.3s',
                      }}
                    />
                  </div>
                  <p
                    style={{
                      margin: '4px 0 0',
                      fontSize: 12,
                      color: '#475569',
                    }}
                  >
                    Synthesising query → SERP fetch → parallel competitor
                    crawls → analysis → clustering → gap → writer
                  </p>
                </div>
              )}
            </div>
          </form>
          {start.error && (
            <div
              style={{
                marginTop: 12,
                color: '#b91c1c',
                fontSize: 13,
              }}
            >
              Run failed: {(start.error as Error).message}
            </div>
          )}
        </CardContent>
      </Card>

      {payload && (
        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 24 }}>
          <TelemetryStrip payload={payload} />
          {payload.warnings?.length > 0 && (
            <WarningsCard warnings={payload.warnings} />
          )}
          <SerpDiscoveryPanel data={payload.stages.serp_discovery} />
          <StructuralAnalyzerPanel
            ours={payload.stages.our_page_analysis}
            competitors={payload.stages.competitor_analyses}
          />
          <PageStructurePanel
            ourStructure={payload.stages.our_structure}
            competitorStructures={payload.stages.competitor_structures}
          />
          <GapReportPanel data={payload.stages.gap_report} />
          <SEOOverlayPanel data={payload.stages.seo_overlay} />
          <RevampDraftPanel
            data={payload.stages.revamp}
            error={payload.stages.revamp_error}
            ourUrl={payload.our_url}
          />
        </div>
      )}

      <Card style={{ marginTop: 32 }}>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.isLoading ? (
            <p style={{ color: '#64748b' }}>Loading…</p>
          ) : (runs.data?.runs ?? []).length === 0 ? (
            <p style={{ color: '#64748b' }}>No runs yet.</p>
          ) : (
            <table style={{ width: '100%', fontSize: 13 }}>
              <thead style={{ textAlign: 'left', color: '#475569' }}>
                <tr>
                  <th style={{ padding: 6 }}>URL</th>
                  <th style={{ padding: 6 }}>Comps</th>
                  <th style={{ padding: 6 }}>Model</th>
                  <th style={{ padding: 6 }}>Cost</th>
                  <th style={{ padding: 6 }}>When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(runs.data?.runs ?? []).map((r) => (
                  <tr
                    key={r.run_id}
                    style={{ borderTop: '1px solid #e2e8f0' }}
                  >
                    <td
                      style={{
                        padding: 6,
                        maxWidth: 360,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                      title={r.our_url}
                    >
                      {r.our_url}
                    </td>
                    <td style={{ padding: 6 }}>{r.competitor_count}</td>
                    <td style={{ padding: 6 }}>{r.model_used || '—'}</td>
                    <td style={{ padding: 6 }}>{fmtUSD(r.cost_usd)}</td>
                    <td
                      style={{ padding: 6, color: '#64748b' }}
                      title={r.created_at}
                    >
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td style={{ padding: 6 }}>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setActiveRunId(r.run_id)}
                      >
                        Re-open
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── sub-panels ──────────────────────────────────────────────────────


function TelemetryStrip({ payload }: { payload: CWV2RunPayload }) {
  const t = payload.telemetry;
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        flexWrap: 'wrap',
        background: '#f1f5f9',
        padding: 12,
        borderRadius: 6,
        fontSize: 13,
      }}
    >
      <span>
        <strong>Run:</strong>{' '}
        <span style={{ fontFamily: 'monospace' }}>{payload.run_id.slice(0, 8)}</span>
      </span>
      <span>
        <strong>Status:</strong>{' '}
        <Badge variant={payload.status === 'complete' ? 'success' : 'error'}>
          {payload.status}
        </Badge>
      </span>
      <span>
        <strong>Wall:</strong> {t?.wall_time_seconds?.toFixed(1)}s
      </span>
      <span>
        <strong>Writer:</strong> {t?.writer_latency_seconds?.toFixed(1)}s
      </span>
      <span>
        <strong>Model:</strong> {t?.model_used || '—'}
      </span>
      <span>
        <strong>Tokens:</strong> {fmtNum(t?.tokens_in)} in /{' '}
        {fmtNum(t?.tokens_out)} out
      </span>
      <span>
        <strong>Cost:</strong> {fmtUSD(t?.cost_usd)}
        {t?.budget_cap_usd ? ` / $${t.budget_cap_usd.toFixed(2)} cap` : ''}
        {t?.degraded ? ' ⚠ degraded' : ''}
      </span>
    </div>
  );
}


function WarningsCard({ warnings }: { warnings: string[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Warnings ({warnings.length})</CardTitle>
      </CardHeader>
      <CardContent>
        <ul style={{ margin: 0, paddingLeft: 20, color: '#475569', fontSize: 13 }}>
          {warnings.map((w, i) => (
            <li key={i} style={{ marginBottom: 4 }}>
              {w}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}


function SerpDiscoveryPanel({ data }: { data: CWV2SerpStage }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>1. SERP discovery</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ marginBottom: 12, fontSize: 13 }}>
          <strong>Synthesised query:</strong>{' '}
          <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4 }}>
            {data.primary_query || '—'}
          </code>
          {data.llm_model && (
            <span style={{ color: '#64748b', marginLeft: 8 }}>
              ({data.llm_model}, {fmtUSD(data.llm_cost_usd)})
            </span>
          )}
        </div>
        {data.bajaj_presence && (
          <div
            style={{
              display: 'inline-block',
              marginBottom: 10,
              padding: '6px 10px',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              background: data.bajaj_presence.found ? '#dcfce7' : '#fef3c7',
              color: data.bajaj_presence.found ? '#166534' : '#92400e',
            }}
            title={data.bajaj_presence.url}
          >
            {data.bajaj_presence.found
              ? `Bajaj ranks${
                  data.bajaj_presence.best_position
                    ? ` #${data.bajaj_presence.best_position}`
                    : ''
                }${
                  data.bajaj_presence.query &&
                  data.bajaj_presence.query !== 'web_search'
                    ? ` for "${data.bajaj_presence.query}"`
                    : ''
                }`
              : 'Bajaj did not rank in the top results for these queries'}
          </div>
        )}
        {(data.all_queries?.length ?? 0) > 0 && (
          <details style={{ marginBottom: 10, fontSize: 13 }}>
            <summary style={{ cursor: 'pointer', color: '#475569' }}>
              {data.all_queries!.length} queries explored
              {data.queries_run?.length
                ? ` · ${data.queries_run.length} run on Google`
                : ''}
              {data.web_search_used ? ' · Claude web search used' : ''}
            </summary>
            <ol style={{ margin: '8px 0 0', paddingLeft: 22, color: '#334155' }}>
              {data.all_queries!.map((q, i) => {
                const ran = data.queries_run?.includes(q);
                return (
                  <li key={i} style={{ marginBottom: 2 }}>
                    <code
                      style={{
                        background: '#f1f5f9',
                        padding: '1px 5px',
                        borderRadius: 3,
                      }}
                    >
                      {q}
                    </code>
                    {ran && (
                      <span style={{ color: '#059669', fontSize: 11, marginLeft: 6 }}>
                        ● fetched
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </details>
        )}
        {data.serp_error && (
          <p style={{ fontSize: 13, color: '#b91c1c' }}>
            SERP error: {data.serp_error}
          </p>
        )}
        <h4 style={{ marginTop: 16, marginBottom: 4 }}>
          Top {data.competitors.length} ranking pages
        </h4>
        {data.our_page_type && (
          <p style={{ margin: '0 0 8px', fontSize: 12, color: '#475569' }}>
            Matching like-for-like: our page is a{' '}
            <strong style={{ color: '#0f172a' }}>{data.our_page_type}</strong>{' '}
            page, so <strong>{data.our_page_type}</strong> competitors are
            compared first (blogs / comparison articles drop to the fallback
            pool).
          </p>
        )}
        <table style={{ width: '100%', fontSize: 12 }}>
          <thead style={{ textAlign: 'left', color: '#475569' }}>
            <tr>
              <th style={{ padding: 4, width: 40 }}>#</th>
              <th style={{ padding: 4 }}>Title / URL</th>
              <th style={{ padding: 4 }}>Domain</th>
              <th style={{ padding: 4 }}>Type</th>
            </tr>
          </thead>
          <tbody>
            {data.competitors.map((c) => (
              <tr key={c.url} style={{ borderTop: '1px solid #e2e8f0' }}>
                <td style={{ padding: 4 }}>{c.position || '—'}</td>
                <td style={{ padding: 4 }}>
                  <div style={{ fontWeight: 500 }}>
                    {c.title || c.domain}
                    {c.source === 'custom' && (
                      <span style={{ marginLeft: 6, fontSize: 10, color: '#7c3aed', fontWeight: 600 }}>
                        ★ custom
                      </span>
                    )}
                    {c.source === 'web_search' && (
                      <span style={{ marginLeft: 6, fontSize: 10, color: '#0891b2' }}>
                        web
                      </span>
                    )}
                  </div>
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: '#1e40af', fontSize: 11 }}
                  >
                    {c.url}
                  </a>
                </td>
                <td style={{ padding: 4, fontFamily: 'monospace', fontSize: 11 }}>
                  {c.domain}
                </td>
                <td style={{ padding: 4 }}>
                  <span
                    style={{
                      fontSize: 11,
                      padding: '1px 6px',
                      borderRadius: 4,
                      background: c.type_match ? '#dcfce7' : '#f1f5f9',
                      color: c.type_match ? '#166534' : '#64748b',
                      fontWeight: c.type_match ? 600 : 400,
                    }}
                    title={c.type_match ? 'Matches our page type' : 'Different page type (fallback)'}
                  >
                    {c.type_match ? '✓ ' : ''}
                    {c.page_type || 'other'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.people_also_ask?.length > 0 && (
          <>
            <h4 style={{ marginTop: 16, marginBottom: 8 }}>
              People Also Ask ({data.people_also_ask.length})
            </h4>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
              {data.people_also_ask.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </>
        )}
        {data.blocked?.length > 0 && (
          <details style={{ marginTop: 12, fontSize: 12, color: '#64748b' }}>
            <summary style={{ cursor: 'pointer' }}>
              {data.blocked.length} blocked (Bajaj / Wikipedia / aggregators)
            </summary>
            <ul style={{ paddingLeft: 20, marginTop: 6 }}>
              {data.blocked.map((b) => (
                <li key={b.url}>
                  #{b.position} {b.domain} — {b.title}
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}


function StructuralAnalyzerPanel({
  ours,
  competitors,
}: {
  ours: CWV2PageAnalysis;
  competitors: { domain: string; analysis: CWV2PageAnalysis }[];
}) {
  const cols = useMemo(
    () => [{ domain: 'OUR PAGE', analysis: ours }, ...competitors],
    [ours, competitors],
  );
  type RowDef = {
    label: string;
    pick: (a: CWV2PageAnalysis) => React.ReactNode;
  };
  const rows: RowDef[] = [
    { label: 'Title (chars)', pick: (a) => `${a.title_length}` },
    { label: 'Meta (chars)', pick: (a) => `${a.meta_description_length}` },
    { label: 'Word count', pick: (a) => fmtNum(a.word_count) },
    { label: 'Reading time', pick: (a) => `${a.reading_time_minutes} min` },
    {
      label: 'Body size',
      pick: (a) => `${(a.content_size_bytes / 1024).toFixed(1)} KB`,
    },
    {
      label: 'Headings (H1/H2/H3/H4+)',
      pick: (a) =>
        `${a.h1_count}/${a.h2_count}/${a.h3_count}/${a.h4_plus_count}`,
    },
    { label: 'Internal links', pick: (a) => `${a.internal_link_count}` },
    {
      label: 'Internal density / 1k',
      pick: (a) => a.internal_link_density_per_1k_words.toFixed(1),
    },
    { label: 'Unique int. targets', pick: (a) => `${a.unique_internal_targets}` },
    {
      label: 'External domains',
      pick: (a) => `${a.unique_external_domains}`,
    },
    {
      label: 'Images',
      pick: (a) => `${a.image_count} (alt ${a.image_alt_coverage_pct.toFixed(0)}%)`,
    },
    { label: 'Videos', pick: (a) => `${a.video_count}` },
    { label: 'FAQ entries', pick: (a) => `${a.faq_question_count}` },
    { label: 'CTAs', pick: (a) => `${a.cta_count}` },
    {
      label: 'Schema',
      pick: (a) =>
        a.trusted_schema_present?.length
          ? a.trusted_schema_present.join(', ')
          : '—',
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>2. Comparative structural analysis</CardTitle>
      </CardHeader>
      <CardContent style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              <th
                style={{
                  textAlign: 'left',
                  padding: 6,
                  borderBottom: '1px solid #cbd5e1',
                }}
              >
                Metric
              </th>
              {cols.map((c, i) => (
                <th
                  key={i}
                  style={{
                    textAlign: 'left',
                    padding: 6,
                    borderBottom: '1px solid #cbd5e1',
                    background: i === 0 ? '#fef3c7' : undefined,
                  }}
                >
                  {c.domain}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} style={{ borderBottom: '1px solid #e2e8f0' }}>
                <td style={{ padding: 6, fontWeight: 500 }}>{r.label}</td>
                {cols.map((c, i) => (
                  <td
                    key={i}
                    style={{
                      padding: 6,
                      background: i === 0 ? '#fef3c7' : undefined,
                    }}
                  >
                    {r.pick(c.analysis)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}


function HeadingTree({
  nodes,
  depth = 0,
}: {
  nodes: CWV2HeadingNode[];
  depth?: number;
}) {
  if (!nodes?.length) return null;
  return (
    <ul style={{ listStyle: 'none', margin: 0, paddingLeft: depth === 0 ? 0 : 16 }}>
      {nodes.map((n, i) => (
        <li key={i} style={{ margin: '2px 0' }}>
          <span
            style={{
              display: 'inline-block',
              minWidth: 28,
              fontSize: 10,
              fontWeight: 700,
              color: '#1e40af',
              fontFamily: 'monospace',
            }}
          >
            H{n.level}
          </span>
          <span style={{ fontSize: 13 }}>{n.text}</span>
          {n.children?.length > 0 && (
            <HeadingTree nodes={n.children} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  );
}


function ClusterCard({ c }: { c: CWV2ClusterSection }) {
  return (
    <div
      style={{
        border: '1px solid #e2e8f0',
        borderLeft: '3px solid #1e40af',
        borderRadius: 4,
        padding: 8,
      }}
    >
      <div style={{ fontWeight: 600, fontSize: 13 }}>{c.name}</div>
      {c.topics_covered?.length ? (
        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
          {c.topics_covered.join(' · ')}
        </div>
      ) : null}
      {c.heading_texts?.length ? (
        <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 11, color: '#475569' }}>
          {c.heading_texts.slice(0, 6).map((h, i) => (
            <li key={i}>{h}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}


function StructureBody({ struct, isOurs }: { struct: CWV2PageStructure; isOurs: boolean }) {
  const hc = struct.heading_counts || { h1: 0, h2: 0, h3: 0, h4_plus: 0 };
  const summaryStyle = { cursor: 'pointer', fontWeight: 600, fontSize: 13 } as const;
  return (
    <div>
      <div
        style={{
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
          fontSize: 12,
          color: '#475569',
          marginBottom: 12,
          background: isOurs ? '#fef3c7' : '#f8fafc',
          padding: 10,
          borderRadius: 4,
        }}
      >
        <span>
          <strong>URL:</strong>{' '}
          <a href={struct.url} target="_blank" rel="noreferrer" style={{ color: '#1e40af' }}>
            {struct.url}
          </a>
        </span>
        <span><strong>Words:</strong> {fmtNum(struct.word_count)}</span>
        <span>
          <strong>Headings H1/H2/H3/H4+:</strong> {hc.h1}/{hc.h2}/{hc.h3}/{hc.h4_plus}
        </span>
        <span>
          <strong>Internal links:</strong> {struct.internal_link_count} (
          {struct.unique_internal_targets} unique)
        </span>
        <span>
          <strong>Images:</strong> {struct.image_count} (alt{' '}
          {Math.round(struct.image_alt_coverage_pct)}%)
        </span>
        {struct.trusted_schema_present?.length ? (
          <span><strong>Schema:</strong> {struct.trusted_schema_present.join(', ')}</span>
        ) : null}
      </div>

      <details open style={{ marginBottom: 10 }}>
        <summary style={summaryStyle}>
          Document outline ({struct.heading_outline?.length ?? 0} top-level)
        </summary>
        <div
          style={{
            marginTop: 8,
            maxHeight: 360,
            overflowY: 'auto',
            border: '1px solid #e2e8f0',
            borderRadius: 4,
            padding: 10,
          }}
        >
          {struct.heading_outline?.length ? (
            <HeadingTree nodes={struct.heading_outline} />
          ) : (
            <em style={{ color: '#94a3b8' }}>No headings captured.</em>
          )}
        </div>
      </details>

      <details style={{ marginBottom: 10 }}>
        <summary style={summaryStyle}>
          Smart content clusters ({struct.clusters?.length ?? 0})
        </summary>
        <div
          style={{
            marginTop: 8,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
            gap: 8,
          }}
        >
          {(struct.clusters || []).map((c, i) => (
            <ClusterCard key={i} c={c} />
          ))}
          {!struct.clusters?.length && (
            <em style={{ color: '#94a3b8' }}>
              No clusters{isOurs ? '' : ' (may have been skipped to stay under budget)'}.
            </em>
          )}
        </div>
      </details>

      <details style={{ marginBottom: 10 }}>
        <summary style={summaryStyle}>
          Internal linking ({struct.internal_links?.length ?? 0} shown)
        </summary>
        <div style={{ marginTop: 8, maxHeight: 300, overflowY: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12 }}>
            <thead style={{ textAlign: 'left', color: '#475569' }}>
              <tr>
                <th style={{ padding: 4 }}>Anchor</th>
                <th style={{ padding: 4 }}>Target</th>
                <th style={{ padding: 4 }}>Section</th>
              </tr>
            </thead>
            <tbody>
              {(struct.internal_links || []).map((l, i) => (
                <tr key={i} style={{ borderTop: '1px solid #e2e8f0' }}>
                  <td style={{ padding: 4 }}>{l.anchor || '—'}</td>
                  <td
                    style={{
                      padding: 4,
                      fontFamily: 'monospace',
                      fontSize: 11,
                      wordBreak: 'break-all',
                    }}
                  >
                    {l.href}
                  </td>
                  <td style={{ padding: 4, color: '#64748b' }}>{l.section || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <details>
        <summary style={summaryStyle}>Images used ({struct.images?.length ?? 0} shown)</summary>
        <div style={{ marginTop: 8, maxHeight: 300, overflowY: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12 }}>
            <thead style={{ textAlign: 'left', color: '#475569' }}>
              <tr>
                <th style={{ padding: 4 }}>Src</th>
                <th style={{ padding: 4 }}>Alt</th>
                <th style={{ padding: 4 }}>Section</th>
              </tr>
            </thead>
            <tbody>
              {(struct.images || []).map((img, i) => (
                <tr key={i} style={{ borderTop: '1px solid #e2e8f0' }}>
                  <td
                    style={{
                      padding: 4,
                      fontFamily: 'monospace',
                      fontSize: 11,
                      wordBreak: 'break-all',
                      maxWidth: 280,
                    }}
                  >
                    {img.src}
                  </td>
                  <td style={{ padding: 4 }}>
                    {img.alt || <span style={{ color: '#b91c1c' }}>(no alt)</span>}
                  </td>
                  <td style={{ padding: 4, color: '#64748b' }}>{img.section || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}


function PageStructurePanel({
  ourStructure,
  competitorStructures,
}: {
  ourStructure?: CWV2PageStructure;
  competitorStructures?: Record<string, CWV2PageStructure>;
}) {
  const entries = useMemo(() => {
    const out: { key: string; label: string; struct: CWV2PageStructure }[] = [];
    if (ourStructure && Object.keys(ourStructure).length > 0) {
      out.push({
        key: '__ours__',
        label: 'OUR PAGE (revamp target)',
        struct: ourStructure,
      });
    }
    for (const [domain, st] of Object.entries(competitorStructures || {})) {
      if (st && Object.keys(st).length > 0) {
        out.push({ key: domain, label: domain, struct: st });
      }
    }
    return out;
  }, [ourStructure, competitorStructures]);

  const [sel, setSel] = useState<string>('');
  const active = entries.find((e) => e.key === sel) || entries[0];

  if (entries.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Page structure — ours vs each competitor</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ marginBottom: 12, fontSize: 13 }}>
          <label style={{ color: '#475569' }}>
            Show structure for:&nbsp;
            <select
              value={active?.key}
              onChange={(e) => setSel(e.target.value)}
              style={{
                padding: '4px 8px',
                border: '1px solid #cbd5e1',
                borderRadius: 4,
                fontSize: 13,
              }}
            >
              {entries.map((e) => (
                <option key={e.key} value={e.key}>
                  {e.label}
                </option>
              ))}
            </select>
          </label>
          <p style={{ margin: '6px 0 0', color: '#94a3b8', fontSize: 12 }}>
            How each page is built — heading hierarchy, LLM topical clusters,
            internal-linking layout, and the images used. Pick a competitor to
            replicate their structure, or "OUR PAGE" to inspect what we're
            revamping.
          </p>
        </div>
        {active && (
          <StructureBody struct={active.struct} isOurs={active.key === '__ours__'} />
        )}
      </CardContent>
    </Card>
  );
}


function GapReportPanel({ data }: { data: CWV2GapReport }) {
  const dims = useMemo(
    () => [...(data.dimensions ?? [])].sort((a, b) => b.priority - a.priority),
    [data.dimensions],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          3. Multi-dimensional gap ({data.competitor_count} competitors)
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.top_priority_actions?.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <h4 style={{ margin: '0 0 8px' }}>Top priority actions</h4>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
              {data.top_priority_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}
        <h4 style={{ margin: '0 0 8px' }}>Dimensions</h4>
        <table style={{ width: '100%', fontSize: 12 }}>
          <thead style={{ textAlign: 'left', color: '#475569' }}>
            <tr>
              <th style={{ padding: 4 }}>Dimension</th>
              <th style={{ padding: 4 }}>Priority</th>
              <th style={{ padding: 4 }}>Headline</th>
            </tr>
          </thead>
          <tbody>
            {dims.map((d) => (
              <DimensionRow key={d.dimension} d={d} />
            ))}
          </tbody>
        </table>
        {data.section_gaps?.length > 0 && (
          <>
            <h4 style={{ margin: '16px 0 8px' }}>
              Section coverage gaps ({data.section_gaps.length})
            </h4>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
              {data.section_gaps.slice(0, 20).map((s, i) => {
                const pr = priorityLabel(s.priority);
                return (
                  <li key={i} style={{ marginBottom: 4 }}>
                    <Badge
                      variant="outline"
                      style={{ color: pr.color, marginRight: 6 }}
                    >
                      {pr.label}
                    </Badge>
                    <strong>{s.section_title}</strong> —{' '}
                    <span style={{ color: '#64748b' }}>
                      {s.competitor_domain}
                    </span>
                    {s.summary && (
                      <div
                        style={{
                          color: '#475569',
                          fontSize: 12,
                          marginLeft: 16,
                        }}
                      >
                        {s.summary}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}


function DimensionRow({ d }: { d: CWV2DimensionGap }) {
  const [open, setOpen] = useState(false);
  const pr = priorityLabel(d.priority);
  return (
    <>
      <tr
        style={{
          borderTop: '1px solid #e2e8f0',
          cursor: 'pointer',
        }}
        onClick={() => setOpen((o) => !o)}
      >
        <td style={{ padding: 4, fontFamily: 'monospace' }}>{d.dimension}</td>
        <td style={{ padding: 4 }}>
          <Badge variant="outline" style={{ color: pr.color }}>
            {pr.label}
          </Badge>
        </td>
        <td style={{ padding: 4 }}>{d.headline}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={3} style={{ padding: '4px 4px 12px 24px', background: '#f8fafc' }}>
            <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
              <span>
                <strong>Ours:</strong> {d.our_value}
              </span>
              <span>
                <strong>Median:</strong> {d.competitor_median}
              </span>
              <span>
                <strong>Max:</strong> {d.competitor_max}
              </span>
              <span>
                <strong>Δ:</strong> {d.delta_vs_median}
              </span>
            </div>
            {d.per_competitor?.length > 0 && (
              <div style={{ marginTop: 4, fontSize: 11, color: '#475569' }}>
                {d.per_competitor
                  .map((p) => `${p.competitor}: ${p.value}`)
                  .join(' · ')}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}


function SEOOverlayPanel({ data }: { data: CWV2SeoOverlay }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>4. SEO best-practices overlay</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 13 }}>
          <span>
            <strong>Score:</strong>{' '}
            <span
              style={{
                fontSize: 18,
                fontWeight: 700,
                color: data.score > 80 ? '#059669' : data.score > 60 ? '#b45309' : '#b91c1c',
              }}
            >
              {data.score}/100
            </span>
          </span>
          <span style={{ color: '#b91c1c' }}>
            <strong>{data.counts.critical}</strong> critical
          </span>
          <span style={{ color: '#b45309' }}>
            <strong>{data.counts.warning}</strong> warning
          </span>
          <span style={{ color: '#475569' }}>
            <strong>{data.counts.notice}</strong> notice
          </span>
        </div>
        <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', fontSize: 13 }}>
          {data.issues.map((i, idx) => (
            <li
              key={idx}
              style={{
                borderLeft: `3px solid ${severityColor(i.severity)}`,
                padding: '6px 12px',
                marginBottom: 6,
                background: '#f8fafc',
              }}
            >
              <div>
                <span style={{ color: severityColor(i.severity), fontWeight: 600 }}>
                  [{i.severity}]
                </span>{' '}
                <code style={{ fontSize: 11 }}>{i.code}</code> — {i.message}
              </div>
              {i.target && (
                <div style={{ color: '#475569', fontSize: 12, marginTop: 2 }}>
                  Target: {i.target}
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}


function RevampDraftPanel({
  data,
  error,
  ourUrl,
}: {
  data: CWV2Revamp;
  error?: string;
  ourUrl: string;
}) {
  const [tab, setTab] = useState<'preview' | 'html' | 'outline' | 'faqs' | 'links' | 'schema' | 'tech'>(
    'preview',
  );

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>5. Revamp draft</CardTitle>
        </CardHeader>
        <CardContent>
          <p style={{ color: '#b91c1c' }}>Writer failed: {error}</p>
        </CardContent>
      </Card>
    );
  }
  if (!data || Object.keys(data).length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>5. Revamp draft</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
            marginBottom: 16,
            paddingBottom: 12,
            borderBottom: '1px dashed #e2e8f0',
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>
            Download full revamp:
          </span>
          <Button variant="outline" size="sm" onClick={() => downloadHtml(data, ourUrl)}>
            HTML
          </Button>
          <Button variant="outline" size="sm" onClick={() => downloadMarkdown(data, ourUrl)}>
            Markdown
          </Button>
          <Button variant="outline" size="sm" onClick={() => downloadDoc(data, ourUrl)}>
            Word (.doc)
          </Button>
          <Button variant="outline" size="sm" onClick={() => exportPdf(data, ourUrl)}>
            PDF
          </Button>
        </div>
        {data.rewrite_strategy && (
          <div
            style={{
              background: '#eff6ff',
              padding: 10,
              borderRadius: 4,
              marginBottom: 16,
              fontSize: 13,
              color: '#1e40af',
            }}
          >
            <strong>Strategy:</strong> {data.rewrite_strategy}
          </div>
        )}
        <div style={{ marginBottom: 16, fontSize: 13 }}>
          {data.title && (
            <div style={{ marginBottom: 8 }}>
              <strong>Title</strong> ({data.title.char_count}ch) — {data.title.text}
              {data.title.rationale && (
                <div style={{ color: '#64748b', fontSize: 12 }}>
                  why: {data.title.rationale}
                </div>
              )}
            </div>
          )}
          {data.meta_description && (
            <div style={{ marginBottom: 8 }}>
              <strong>Meta</strong> ({data.meta_description.char_count}ch) —{' '}
              {data.meta_description.text}
              {data.meta_description.rationale && (
                <div style={{ color: '#64748b', fontSize: 12 }}>
                  why: {data.meta_description.rationale}
                </div>
              )}
            </div>
          )}
          {data.h1 && (
            <div>
              <strong>H1</strong> — {data.h1.text}
            </div>
          )}
        </div>
        <div
          style={{
            display: 'flex',
            gap: 4,
            borderBottom: '1px solid #cbd5e1',
            marginBottom: 12,
          }}
        >
          {(
            [
              ['preview', 'Body preview'],
              ['html', 'Raw HTML'],
              ['outline', `Outline (${data.outline?.length ?? 0})`],
              ['faqs', `FAQs (${data.faqs?.length ?? 0})`],
              ['links', `Internal links (${data.internal_links_plan?.length ?? 0})`],
              ['schema', `JSON-LD (${data.json_ld_blocks?.length ?? 0})`],
              ['tech', `Tech (${data.tech_recommendations?.length ?? 0})`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                padding: '6px 12px',
                border: 'none',
                background: tab === key ? '#1e40af' : 'transparent',
                color: tab === key ? 'white' : '#475569',
                borderRadius: '4px 4px 0 0',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === 'preview' && (
          <div
            style={{
              border: '1px solid #e2e8f0',
              borderRadius: 4,
              padding: 16,
              background: 'white',
              maxHeight: 600,
              overflowY: 'auto',
            }}
            dangerouslySetInnerHTML={{ __html: data.body_html || '' }}
          />
        )}
        {tab === 'html' && (
          <textarea
            readOnly
            value={data.body_html || ''}
            style={{
              width: '100%',
              minHeight: 400,
              fontFamily: 'monospace',
              fontSize: 11,
              padding: 8,
            }}
          />
        )}
        {tab === 'outline' && (
          <ol style={{ fontSize: 13 }}>
            {(data.outline ?? []).map((o, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                <strong>H{o.level}</strong> {o.heading}
                {o.estimated_words && (
                  <span style={{ color: '#64748b' }}>
                    {' '}
                    (~{o.estimated_words} words)
                  </span>
                )}
                {o.closes_gaps && o.closes_gaps.length > 0 && (
                  <div style={{ fontSize: 11, color: '#475569' }}>
                    closes: {o.closes_gaps.join(', ')}
                  </div>
                )}
                {o.rationale && (
                  <div style={{ fontSize: 12, color: '#64748b' }}>
                    why: {o.rationale}
                  </div>
                )}
                {o.sub_headings && o.sub_headings.length > 0 && (
                  <ul style={{ paddingLeft: 16, fontSize: 12, color: '#475569' }}>
                    {o.sub_headings.map((s, j) => (
                      <li key={j}>
                        H{s.level} {s.heading}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        )}
        {tab === 'faqs' && (
          <ul style={{ fontSize: 13, paddingLeft: 20 }}>
            {(data.faqs ?? []).map((f, i) => (
              <li key={i} style={{ marginBottom: 12 }}>
                <strong>{f.question}</strong>{' '}
                <Badge variant="outline" style={{ fontSize: 10 }}>
                  {f.source}
                </Badge>
                <div style={{ color: '#475569', marginTop: 4 }}>{f.answer}</div>
              </li>
            ))}
          </ul>
        )}
        {tab === 'links' && (
          <table style={{ width: '100%', fontSize: 12 }}>
            <thead style={{ textAlign: 'left', color: '#475569' }}>
              <tr>
                <th style={{ padding: 4 }}>Anchor</th>
                <th style={{ padding: 4 }}>Target</th>
                <th style={{ padding: 4 }}>Section</th>
                <th style={{ padding: 4 }}>Why</th>
              </tr>
            </thead>
            <tbody>
              {(data.internal_links_plan ?? []).map((l, i) => (
                <tr key={i} style={{ borderTop: '1px solid #e2e8f0' }}>
                  <td style={{ padding: 4 }}>{l.anchor}</td>
                  <td style={{ padding: 4, fontFamily: 'monospace', fontSize: 11 }}>
                    {l.target_url}
                  </td>
                  <td style={{ padding: 4, color: '#64748b' }}>{l.section}</td>
                  <td style={{ padding: 4, color: '#64748b' }}>
                    {l.rationale}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === 'schema' && (
          <div>
            {(data.json_ld_blocks ?? []).map((b, i) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <strong>{b.type}</strong>
                <pre
                  style={{
                    background: '#0f172a',
                    color: '#e2e8f0',
                    padding: 12,
                    borderRadius: 4,
                    fontSize: 11,
                    overflowX: 'auto',
                  }}
                >
                  {JSON.stringify(b.json_ld, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
        {tab === 'tech' && (
          <ul style={{ fontSize: 13, paddingLeft: 20 }}>
            {(data.tech_recommendations ?? []).map((r, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {r}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
