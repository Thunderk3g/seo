/**
 * ContentWriterPage — `/content-writer`.
 *
 * Page-revamp workflow: operator enters ONE Bajaj URL (+ optional
 * free-text prompt). Backend (`/seo/content-writer/revamp/`) live-crawls
 * the URL, scans every competitor brand in the DB for a counterpart
 * page, refreshes stale rows, pulls CWV + Semrush, and runs the Groq
 * agent. We get back a full improved-version proposal: title, meta,
 * heading outline, body sections, FAQ, CTAs, internal-link
 * recommendations, tech findings, plus a publish-ready HTML draft and
 * a Markdown mirror.
 *
 * UI structure:
 *   1. Input card — URL + optional prompt + submit.
 *   2. Staged progress card (visible during in-flight mutation).
 *   3. Telemetry strip — competitors scanned/matched, cost, tokens,
 *      critic accept/reject counts.
 *   4. Competitor counterparts table — what we compared against and
 *      where each row came from (DB vs live refresh).
 *   5. Rewrite panels — title, meta, headings, body sections, FAQ,
 *      CTAs, internal links, tech recommendations. Each citation pill
 *      pops a "source evidence" inspector.
 *   6. Improved HTML — full publish-ready HTML in its own section, with
 *      a live preview + raw code + copy buttons.
 *   7. Improved Markdown — same content as a Markdown blob with copy.
 *   8. Recent proposals table — re-open any past rewrite.
 */
import { useEffect, useMemo, useState } from 'react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import {
  useContentWriterProposal,
  useContentWriterProposals,
  useRevampPage,
  type CitedBodySection,
  type CitedCta,
  type CitedFaqEntry,
  type CitedHeading,
  type CitedLink,
  type CitedString,
  type CompetitorMatch,
  type CompetitorGapSummary,
  type ContentRewriteProposal,
  type RewriteProposalBody,
  type TechRecommendation,
} from '../api/hooks/useContentWriter';
import { useCompetitorPageStructure } from '../api/hooks/useCompetitorDetail';

const PROGRESS_STAGES = [
  { at: 0, label: 'Live-crawling your URL' },
  { at: 0.15, label: 'Scanning DB for competitor counterparts' },
  { at: 0.3, label: 'Refreshing stale competitor pages' },
  { at: 0.55, label: 'Measuring Core Web Vitals (mobile + desktop)' },
  { at: 0.75, label: 'Pulling Semrush ranking keywords' },
  { at: 0.85, label: 'AI agent writing the improved version' },
];

// Assumed total wall time used to project the progress bar.
const EXPECTED_DURATION_S = 35;

export default function ContentWriterPage() {
  const proposals = useContentWriterProposals();
  const revamp = useRevampPage();

  const [urlInput, setUrlInput] = useState('');
  const [promptInput, setPromptInput] = useState('');
  const [activeProposalId, setActiveProposalId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // Drive elapsed-time counter while the request is in flight so the
  // staged-progress UI can advance.
  useEffect(() => {
    if (!revamp.isPending) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const tick = window.setInterval(() => {
      setElapsed((Date.now() - start) / 1000);
    }, 250);
    return () => window.clearInterval(tick);
  }, [revamp.isPending]);

  function handleSubmit() {
    const u = urlInput.trim();
    if (!u) return;
    revamp.mutate(
      { our_url: u, prompt: promptInput.trim() || undefined },
      { onSuccess: (data) => setActiveProposalId(data.id) },
    );
  }

  return (
    <div className="bajaj-ui p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-brand-text">
          Content Writer · Page Revamp
        </h1>
        <p className="mt-1 text-sm text-brand-text-3">
          Paste one Bajaj URL. We live-crawl it, scan every competitor brand
          in the DB for the same page, pull CWV + Semrush, and the AI agent
          rewrites it to outperform them. The optional prompt steers the
          rewrite (e.g. "compare only with hdfclife", "make it shorter",
          "focus on tax savings").
        </p>
      </header>

      {/* ── 1. Input ───────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Revamp this page</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-brand-text-3">
              Bajaj page URL
            </label>
            <input
              type="url"
              inputMode="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="https://www.bajajlifeinsurance.com/term-insurance-plans.html"
              className="w-full rounded border border-brand-border bg-white p-2 font-mono text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-brand-text-3">
              Prompt — optional (instructions, specific competitor, tone…)
            </label>
            <textarea
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="e.g. compare with hdfclife only, focus on the 1-crore term plan angle, keep the meta under 155 chars"
              rows={3}
              className="w-full rounded border border-brand-border bg-white p-2 text-sm"
            />
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={handleSubmit}
              disabled={!urlInput.trim() || revamp.isPending}
            >
              {revamp.isPending ? 'Revamping…' : 'Revamp page'}
            </Button>
            {revamp.error && (
              <span className="text-xs text-severity-error">
                {(revamp.error as Error).message}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── 2. Staged progress while in flight ─────────────────── */}
      {revamp.isPending && (
        <StagedProgress elapsed={elapsed} />
      )}

      {/* ── 3-7. Result ────────────────────────────────────────── */}
      {activeProposalId && !revamp.isPending && (
        <ProposalView proposalId={activeProposalId} />
      )}

      {/* ── 8. Recent proposals ─────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Recent proposals</CardTitle>
        </CardHeader>
        <CardContent>
          {proposals.isLoading && (
            <div className="text-sm text-brand-text-3">Loading…</div>
          )}
          {proposals.data && proposals.data.proposals.length === 0 && (
            <div className="text-sm text-brand-text-3">
              No proposals yet. Generate your first one above.
            </div>
          )}
          {proposals.data && proposals.data.proposals.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-brand-text-3">
                  <tr>
                    <th className="px-2 py-1 text-left">When</th>
                    <th className="px-2 py-1 text-left">URL</th>
                    <th className="px-2 py-1 text-left">Model</th>
                    <th className="px-2 py-1 text-right">Accepted</th>
                    <th className="px-2 py-1 text-right">Rejected</th>
                    <th className="px-2 py-1 text-right">Cost</th>
                    <th className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody>
                  {proposals.data.proposals.map((p) => (
                    <tr
                      key={p.id}
                      className="border-t border-brand-border hover:bg-brand-surface-2"
                    >
                      <td className="px-2 py-1 text-brand-text-3">
                        {new Date(p.created_at).toLocaleString()}
                      </td>
                      <td className="px-2 py-1 break-all">{p.our_url}</td>
                      <td className="px-2 py-1 text-brand-text-3">
                        {p.model_used || '—'}
                      </td>
                      <td className="px-2 py-1 text-right">{p.accepted}</td>
                      <td className="px-2 py-1 text-right">
                        {p.rejected > 0 ? (
                          <span className="text-severity-warning">
                            {p.rejected}
                          </span>
                        ) : (
                          p.rejected
                        )}
                      </td>
                      <td className="px-2 py-1 text-right">
                        ${p.cost_usd.toFixed(4)}
                      </td>
                      <td className="px-2 py-1 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setActiveProposalId(p.id)}
                        >
                          Open
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Staged progress ──────────────────────────────────────────────────

function StagedProgress({ elapsed }: { elapsed: number }) {
  const pct = Math.min(elapsed / EXPECTED_DURATION_S, 0.96);
  const currentIdx =
    PROGRESS_STAGES.findIndex((_, i, arr) => {
      const next = arr[i + 1];
      if (!next) return true;
      return pct < next.at;
    }) ?? 0;
  return (
    <Card>
      <CardContent className="py-5">
        <div className="mb-3 flex items-baseline justify-between">
          <div className="text-sm font-semibold text-brand-text">
            {PROGRESS_STAGES[currentIdx].label}…
          </div>
          <div className="text-xs tabular-nums text-brand-text-3">
            {elapsed.toFixed(1)}s
          </div>
        </div>
        <div className="h-2 overflow-hidden rounded bg-brand-surface-2">
          <div
            className="h-full rounded bg-brand-accent transition-all duration-300"
            style={{ width: `${pct * 100}%` }}
          />
        </div>
        <ol className="mt-4 space-y-1 text-xs text-brand-text-3">
          {PROGRESS_STAGES.map((s, i) => (
            <li
              key={s.label}
              className={
                i < currentIdx
                  ? 'text-brand-text line-through'
                  : i === currentIdx
                    ? 'font-semibold text-brand-text'
                    : ''
              }
            >
              {i < currentIdx ? '✓ ' : i === currentIdx ? '› ' : '  '}
              {s.label}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

// ── Proposal result view ─────────────────────────────────────────────

function ProposalView({ proposalId }: { proposalId: string }) {
  const { data } = useContentWriterProposal(proposalId);
  if (!data) {
    return (
      <Card>
        <CardContent className="py-5 text-sm text-brand-text-3">
          Loading proposal…
        </CardContent>
      </Card>
    );
  }
  if (data.error) {
    return (
      <Card className="border-severity-error">
        <CardContent className="py-4">
          <div className="font-medium text-severity-error">
            Revamp failed
          </div>
          <div className="mt-1 text-xs text-brand-text-3">{data.error}</div>
        </CardContent>
      </Card>
    );
  }
  const proposed = (data.generated_proposal || {}) as RewriteProposalBody;
  const ev = (data.evidence_dict || {}) as Record<string, unknown>;
  const matches = data.competitor_matches || [];
  const tel = data.telemetry;

  return (
    <>
      <TelemetryStrip data={data} />
      {matches.length > 0 && <MatchesTable matches={matches} />}
      {matches.length > 0 && <ClusterContextSection matches={matches} />}
      {tel && tel.warnings && tel.warnings.length > 0 && (
        <WarningTile warnings={tel.warnings} />
      )}
      {proposed.competitor_gap_summary && proposed.competitor_gap_summary.length > 0 && (
        <GapSummary rows={proposed.competitor_gap_summary} />
      )}
      <RewritePanels proposed={proposed} evidence={ev} />
      {proposed.improved_html && (
        <HtmlOutput html={proposed.improved_html} />
      )}
      {proposed.improved_markdown && (
        <MarkdownOutput markdown={proposed.improved_markdown} />
      )}
    </>
  );
}

// ── Cluster-context section ─────────────────────────────────────────
//
// For each matched competitor: pull their LLM-clustered page structure
// (re-uses the same endpoint that powers CompetitorPageStructureSection
// on /competitors/<domain>/) and highlight which cluster the matched
// URL belongs to. The operator sees not just "we compared with HDFC's
// term-insurance-plans" but "that page sits in their Term Insurance
// Products cluster which has these 3 sibling pages we could also
// link to".

function ClusterContextSection({ matches }: { matches: CompetitorMatch[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Page-structure context · how each match sits in their site
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="text-xs text-brand-text-3">
          The LLM clusters each competitor's pages into named topical
          buckets. We highlight the cluster the matched URL belongs to,
          plus its siblings — useful for spotting related pages we
          might cover or internal-link to.
        </div>
        {matches.map((m) => (
          <CompetitorClusterCard key={m.brand} match={m} />
        ))}
      </CardContent>
    </Card>
  );
}

function CompetitorClusterCard({ match }: { match: CompetitorMatch }) {
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading, isError, error } = useCompetitorPageStructure(
    match.brand,
    { maxPages: 60 },
  );

  // Find the cluster containing the matched URL.
  const matchedCluster = useMemo(() => {
    if (!data?.clusters) return null;
    for (const c of data.clusters) {
      if (c.pages.some((p) => p.url === match.url)) {
        return c;
      }
    }
    return null;
  }, [data, match.url]);

  return (
    <div className="overflow-hidden rounded border border-brand-border bg-white">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-3 px-3 py-2 text-left"
      >
        <span className="w-3 text-xs text-brand-text-3">
          {expanded ? '▾' : '▸'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold text-brand-text">
              {match.brand}
            </span>
            <span className="text-[10px] text-brand-text-3">
              {(match.confidence * 100).toFixed(0)}% match
            </span>
          </div>
          {isLoading && (
            <div className="text-xs text-brand-text-3">
              Building page structure…
            </div>
          )}
          {isError && (
            <div className="text-xs text-brand-text-3">
              Failed: {error instanceof Error ? error.message : 'unknown'}
            </div>
          )}
          {!isLoading && !isError && matchedCluster && (
            <div className="text-xs text-brand-text-2">
              Sits in{' '}
              <span className="font-semibold text-brand-accent">
                {matchedCluster.name}
              </span>{' '}
              · {matchedCluster.pages.length} sibling page
              {matchedCluster.pages.length === 1 ? '' : 's'}
            </div>
          )}
          {!isLoading && !isError && !matchedCluster && data && (
            <div className="text-xs text-brand-text-3">
              URL not found in structure scan (may be outside the top{' '}
              {data.total_pages_sampled} pages).
            </div>
          )}
        </div>
        {data && (
          <span className="shrink-0 text-[10px] text-brand-text-3">
            {data.total_pages_sampled}/{data.total_pages_in_corpus} pages ·{' '}
            {data.clusters.length} clusters
          </span>
        )}
      </button>
      {expanded && data && data.clusters && data.clusters.length > 0 && (
        <div className="border-t border-brand-border bg-brand-surface-2 px-3 py-2">
          <div className="space-y-2">
            {data.clusters.map((c) => {
              const isMatched = matchedCluster?.cluster_id === c.cluster_id;
              return (
                <div
                  key={c.cluster_id}
                  className={`rounded border bg-white p-2 ${
                    isMatched
                      ? 'border-brand-accent shadow-sm'
                      : 'border-brand-border'
                  }`}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-semibold text-brand-text">
                      {c.name}
                    </span>
                    <span className="text-[10px] text-brand-text-3">
                      {c.pages.length} page
                      {c.pages.length === 1 ? '' : 's'}
                    </span>
                    {isMatched && (
                      <span className="rounded bg-brand-accent px-1.5 py-0.5 text-[9px] font-semibold uppercase text-white">
                        matched URL here
                      </span>
                    )}
                  </div>
                  {c.rationale && (
                    <div className="mt-0.5 text-[10px] italic text-brand-text-3">
                      {c.rationale}
                    </div>
                  )}
                  <ul className="mt-1 space-y-0.5">
                    {c.pages.slice(0, 5).map((p) => {
                      const isMatchedUrl = p.url === match.url;
                      return (
                        <li key={p.url} className="text-[11px]">
                          <a
                            href={p.url}
                            target="_blank"
                            rel="noreferrer"
                            className={
                              isMatchedUrl
                                ? 'font-mono font-semibold text-brand-accent hover:underline'
                                : 'font-mono text-brand-text-2 hover:underline'
                            }
                            title={p.url}
                          >
                            {p.title || '(untitled)'}
                          </a>
                        </li>
                      );
                    })}
                    {c.pages.length > 5 && (
                      <li className="text-[10px] italic text-brand-text-3">
                        + {c.pages.length - 5} more
                      </li>
                    )}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function TelemetryStrip({ data }: { data: ContentRewriteProposal }) {
  const accepted = data.critic_verdict?.accepted ?? 0;
  const rejected = data.critic_verdict?.rejected ?? 0;
  const tel = data.telemetry;
  return (
    <Card>
      <CardContent className="flex flex-wrap items-baseline gap-x-6 gap-y-2 py-3 text-xs">
        <Stat label="Competitors scanned" value={tel?.competitors_scanned ?? '—'} />
        <Stat label="Counterparts matched" value={tel?.competitors_matched ?? matches_count_from(data)} />
        <Stat
          label="Backed"
          value={accepted}
          tone="success"
        />
        <Stat
          label="Dropped (unbacked)"
          value={rejected}
          tone={rejected > 0 ? 'warn' : 'neutral'}
        />
        <Stat label="Model" value={data.model_used || '—'} />
        <Stat label="Cost" value={`$${data.cost_usd.toFixed(4)}`} />
        <Stat label="Tokens" value={(data.tokens_in + data.tokens_out).toLocaleString()} />
      </CardContent>
    </Card>
  );
}

function matches_count_from(data: ContentRewriteProposal): number {
  return data.competitor_matches?.length ?? data.competitor_urls.length;
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string | number;
  tone?: 'neutral' | 'success' | 'warn';
}) {
  const color =
    tone === 'success'
      ? 'text-severity-success'
      : tone === 'warn'
        ? 'text-severity-warning'
        : 'text-brand-text';
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-brand-text-3">
        {label}
      </div>
      <div className={`mt-0.5 text-sm font-semibold ${color}`}>{value}</div>
    </div>
  );
}

function MatchesTable({ matches }: { matches: CompetitorMatch[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Counterparts compared ({matches.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-brand-text-3">
              <tr>
                <th className="px-2 py-1 text-left">Brand</th>
                <th className="px-2 py-1 text-left">Matched URL</th>
                <th className="px-2 py-1 text-left">Title</th>
                <th className="px-2 py-1 text-right">Confidence</th>
                <th className="px-2 py-1 text-right">Words</th>
                <th className="px-2 py-1 text-left">Source</th>
              </tr>
            </thead>
            <tbody>
              {matches.map((m) => (
                <tr
                  key={`${m.brand}-${m.url}`}
                  className="border-t border-brand-border align-top"
                >
                  <td className="px-2 py-1 font-medium text-brand-text">
                    {m.brand}
                  </td>
                  <td className="px-2 py-1 max-w-md break-all">
                    <a
                      href={m.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-brand-accent hover:underline"
                    >
                      {m.url}
                    </a>
                  </td>
                  <td className="px-2 py-1 text-brand-text-2 max-w-sm truncate">
                    {m.title}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    {(m.confidence * 100).toFixed(0)}%
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    {m.word_count.toLocaleString()}
                  </td>
                  <td className="px-2 py-1">
                    <span
                      className={
                        m.source === 'live'
                          ? 'rounded bg-severity-warning-soft px-1.5 py-0.5 text-[10px] font-semibold text-severity-warning'
                          : 'rounded bg-brand-surface-2 px-1.5 py-0.5 text-[10px] font-semibold text-brand-text-3'
                      }
                    >
                      {m.source === 'live' ? 'live refresh' : 'db cache'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function WarningTile({ warnings }: { warnings: string[] }) {
  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
      <div className="font-semibold">Notes from the orchestrator</div>
      <ul className="mt-1 space-y-0.5">
        {warnings.map((w, i) => (
          <li key={i}>• {w}</li>
        ))}
      </ul>
    </div>
  );
}

function GapSummary({ rows }: { rows: CompetitorGapSummary[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Gap analysis</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {rows.map((r, i) => (
            <li
              key={i}
              className="rounded border border-brand-border bg-brand-surface-2 px-3 py-2"
            >
              <div className="text-xs font-semibold uppercase text-brand-text-3">
                {r.brand}
              </div>
              <div className="mt-0.5 text-brand-text">{r.gap}</div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// ── Rewrite panels ───────────────────────────────────────────────────

function RewritePanels({
  proposed,
  evidence,
}: {
  proposed: RewriteProposalBody;
  evidence: Record<string, unknown>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Improved version</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {proposed.proposed_title && (
          <CitedField
            label="Title"
            cited={proposed.proposed_title}
            evidence={evidence}
          />
        )}
        {proposed.proposed_meta_description && (
          <CitedField
            label="Meta description"
            cited={proposed.proposed_meta_description}
            evidence={evidence}
            multiline
          />
        )}
        {proposed.proposed_headings && proposed.proposed_headings.length > 0 && (
          <HeadingsList
            headings={proposed.proposed_headings}
            evidence={evidence}
          />
        )}
        {proposed.proposed_body_sections &&
          proposed.proposed_body_sections.length > 0 && (
            <BodySections
              sections={proposed.proposed_body_sections}
              evidence={evidence}
            />
          )}
        {proposed.proposed_faq && proposed.proposed_faq.length > 0 && (
          <FaqList entries={proposed.proposed_faq} evidence={evidence} />
        )}
        {proposed.proposed_ctas && proposed.proposed_ctas.length > 0 && (
          <CtaList ctas={proposed.proposed_ctas} evidence={evidence} />
        )}
        {proposed.proposed_internal_links &&
          proposed.proposed_internal_links.length > 0 && (
            <InternalLinks
              links={proposed.proposed_internal_links}
              evidence={evidence}
            />
          )}
        {proposed.tech_recommendations &&
          proposed.tech_recommendations.length > 0 && (
            <TechRecs
              recs={proposed.tech_recommendations}
              evidence={evidence}
            />
          )}
        {proposed.overall_rationale && (
          <div className="rounded border border-brand-border bg-brand-surface-2 p-3 text-sm">
            <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
              Rewrite strategy
            </div>
            <div className="text-brand-text-2">{proposed.overall_rationale}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CitedField({
  label,
  cited,
  evidence,
  multiline = false,
}: {
  label: string;
  cited: CitedString;
  evidence: Record<string, unknown>;
  multiline?: boolean;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        {label}
      </div>
      <div
        className={`rounded border border-brand-border bg-white p-3 text-sm text-brand-text ${
          multiline ? 'whitespace-pre-wrap' : ''
        }`}
      >
        {cited.text}
      </div>
      <CitationPill ref_={cited.source_ref} evidence={evidence} />
      {cited.rationale && (
        <div className="mt-1 text-xs italic text-brand-text-3">
          {cited.rationale}
        </div>
      )}
    </div>
  );
}

function HeadingsList({
  headings,
  evidence,
}: {
  headings: CitedHeading[];
  evidence: Record<string, unknown>;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        Heading outline ({headings.length})
      </div>
      <ul className="space-y-1">
        {headings.map((h, i) => {
          const indent = Math.max(0, (h.level - 1) * 16);
          const sizeCls =
            h.level === 1
              ? 'text-base font-bold text-brand-text'
              : h.level === 2
                ? 'text-sm font-semibold text-brand-text'
                : 'text-sm text-brand-text-2';
          return (
            <li key={i} style={{ paddingLeft: indent }}>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] uppercase text-brand-text-3">
                  h{h.level}
                </span>
                <span className={sizeCls}>{h.text}</span>
              </div>
              <div className="ml-7">
                <CitationPill ref_={h.source_ref} evidence={evidence} />
                {h.rationale && (
                  <span className="ml-2 text-[10px] italic text-brand-text-3">
                    {h.rationale}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BodySections({
  sections,
  evidence,
}: {
  sections: CitedBodySection[];
  evidence: Record<string, unknown>;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        Body sections ({sections.length})
      </div>
      <div className="space-y-3">
        {sections.map((s, i) => (
          <div
            key={i}
            className="rounded border border-brand-border bg-white p-3"
          >
            <div className="text-sm font-semibold text-brand-text">
              {s.heading_text}
            </div>
            <div className="mt-2 space-y-2 text-sm text-brand-text-2">
              {(s.paragraphs || []).map((p, j) => (
                <p key={j} className="leading-relaxed">
                  {p}
                </p>
              ))}
            </div>
            <CitationPill ref_={s.source_ref} evidence={evidence} />
            {s.rationale && (
              <div className="mt-1 text-xs italic text-brand-text-3">
                {s.rationale}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function FaqList({
  entries,
  evidence,
}: {
  entries: CitedFaqEntry[];
  evidence: Record<string, unknown>;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        FAQ ({entries.length})
      </div>
      <div className="space-y-2">
        {entries.map((f, i) => (
          <details
            key={i}
            className="rounded border border-brand-border bg-white open:bg-brand-surface-2"
          >
            <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-brand-text">
              {f.question}
            </summary>
            <div className="border-t border-brand-border px-3 py-2 text-sm text-brand-text-2">
              {f.answer}
              <div className="mt-1">
                <CitationPill ref_={f.source_ref} evidence={evidence} />
              </div>
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

function CtaList({
  ctas,
  evidence,
}: {
  ctas: CitedCta[];
  evidence: Record<string, unknown>;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        CTAs ({ctas.length})
      </div>
      <div className="flex flex-wrap gap-2">
        {ctas.map((c, i) => (
          <div
            key={i}
            className="flex items-center gap-2 rounded border border-brand-border bg-white px-3 py-2 text-sm"
          >
            <span className="font-semibold text-brand-accent">{c.text}</span>
            {c.placement && (
              <span className="text-[10px] uppercase text-brand-text-3">
                · {c.placement}
              </span>
            )}
            <CitationPill ref_={c.source_ref} evidence={evidence} />
          </div>
        ))}
      </div>
    </div>
  );
}

function InternalLinks({
  links,
  evidence,
}: {
  links: CitedLink[];
  evidence: Record<string, unknown>;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        Internal-link recommendations ({links.length})
      </div>
      <ul className="space-y-1 text-xs">
        {links.map((l, i) => (
          <li
            key={i}
            className="flex flex-wrap items-baseline gap-2 rounded border border-brand-border bg-white px-2 py-1"
          >
            <span className="font-semibold text-brand-text">{l.anchor}</span>
            <span className="text-brand-text-3">→</span>
            <a
              href={l.target_url}
              target="_blank"
              rel="noreferrer"
              className="break-all font-mono text-brand-accent hover:underline"
            >
              {l.target_url}
            </a>
            {l.section && (
              <span className="text-[10px] uppercase text-brand-text-3">
                · {l.section}
              </span>
            )}
            <CitationPill ref_={l.source_ref} evidence={evidence} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function TechRecs({
  recs,
  evidence,
}: {
  recs: TechRecommendation[];
  evidence: Record<string, unknown>;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase text-brand-text-3">
        Technical recommendations ({recs.length})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-brand-text-3">
            <tr>
              <th className="px-2 py-1 text-left">Area</th>
              <th className="px-2 py-1 text-left">Current</th>
              <th className="px-2 py-1 text-left">Target</th>
              <th className="px-2 py-1 text-left">Suggestion</th>
              <th className="px-2 py-1" />
            </tr>
          </thead>
          <tbody>
            {recs.map((r, i) => (
              <tr key={i} className="border-t border-brand-border align-top">
                <td className="px-2 py-1 font-semibold uppercase text-brand-text">
                  {r.area}
                </td>
                <td className="px-2 py-1 tabular-nums">{r.current || '—'}</td>
                <td className="px-2 py-1 tabular-nums">{r.target || '—'}</td>
                <td className="px-2 py-1 text-brand-text-2">{r.suggestion}</td>
                <td className="px-2 py-1">
                  <CitationPill ref_={r.source_ref} evidence={evidence} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Citation pill ────────────────────────────────────────────────────

function CitationPill({
  ref_,
  evidence,
}: {
  ref_: string;
  evidence: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);
  if (!ref_) return null;
  const raw = evidence[ref_];
  const display = useMemo(() => {
    if (raw === undefined || raw === null) return '— evidence missing —';
    if (typeof raw === 'string') return raw;
    return JSON.stringify(raw, null, 2);
  }, [raw]);
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mt-1 inline-block rounded bg-brand-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-brand-text-3 hover:bg-brand-accent-soft hover:text-brand-accent"
        title="Click to show source evidence"
      >
        ↳ {ref_}
      </button>
      {open && (
        <span className="ml-1 max-w-md whitespace-pre-wrap rounded border border-brand-border bg-white px-2 py-1 font-mono text-[10px] text-brand-text-2">
          {display}
        </span>
      )}
    </span>
  );
}

// ── HTML / Markdown output ───────────────────────────────────────────

function HtmlOutput({ html }: { html: string }) {
  const [view, setView] = useState<'preview' | 'code'>('preview');
  const [copied, setCopied] = useState(false);
  return (
    <Card>
      <CardHeader>
        <div className="flex items-baseline justify-between">
          <CardTitle>Improved HTML</CardTitle>
          <div className="flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded border border-brand-border">
              <button
                type="button"
                onClick={() => setView('preview')}
                className={`px-3 py-1 text-xs font-semibold ${
                  view === 'preview'
                    ? 'bg-brand-accent text-white'
                    : 'bg-white text-brand-text-2'
                }`}
              >
                Preview
              </button>
              <button
                type="button"
                onClick={() => setView('code')}
                className={`border-l border-brand-border px-3 py-1 text-xs font-semibold ${
                  view === 'code'
                    ? 'bg-brand-accent text-white'
                    : 'bg-white text-brand-text-2'
                }`}
              >
                Code
              </button>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                await navigator.clipboard.writeText(html);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? 'Copied' : 'Copy HTML'}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {view === 'preview' ? (
          <div
            className="prose max-w-none rounded border border-brand-border bg-white p-4 text-sm text-brand-text"
            // The agent's output is grounded by the critic; still scope
            // visual rendering inside .prose so it doesn't leak styles.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="max-h-[480px] overflow-auto rounded border border-brand-border bg-brand-surface-2 p-3 font-mono text-[11px] leading-relaxed text-brand-text-2">
            {html}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

function MarkdownOutput({ markdown }: { markdown: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Card>
      <CardHeader>
        <div className="flex items-baseline justify-between">
          <CardTitle>Improved Markdown</CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              await navigator.clipboard.writeText(markdown);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? 'Copied' : 'Copy Markdown'}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <pre className="max-h-[480px] overflow-auto rounded border border-brand-border bg-brand-surface-2 p-3 font-mono text-[12px] leading-relaxed text-brand-text-2 whitespace-pre-wrap">
          {markdown}
        </pre>
      </CardContent>
    </Card>
  );
}
