/**
 * ContentWriterPage — `/content-writer`.
 *
 * Operator-facing tool that asks the ContentWriter agent to propose a
 * rewrite for one of our crawled pages, grounded in:
 *
 *   * our current title / meta / headings / internal links,
 *   * zero or more competitor URLs we have deep-crawled, and
 *   * an optional list of target keywords.
 *
 * Every proposed string carries a ``source_ref`` and a backend
 * deterministic pass drops anything that doesn't resolve into the
 * evidence dict. The UI surfaces each backed line with a source pill
 * the operator can click to inspect the source evidence — so "the AI
 * wrote this" is always traceable to a real signal.
 *
 * Side-by-side diff layout: left column is the current page (title,
 * meta, headings, internal links). Right column is the rewrite, each
 * line accompanied by a citation pill. Bottom panel lists anything
 * the critic rejected (with the reason) so the operator can see what
 * the model tried to hallucinate.
 */
import { useState } from 'react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import {
  useContentWriterOurPages,
  useContentWriterProposals,
  useContentWriterProposal,
  useGenerateRewrite,
  type CitedHeading,
  type CitedLink,
  type CitedString,
} from '../api/hooks/useContentWriter';

export default function ContentWriterPage() {
  const ourPages = useContentWriterOurPages();
  const proposals = useContentWriterProposals();
  const generate = useGenerateRewrite();

  const [selectedUrl, setSelectedUrl] = useState<string>('');
  const [competitorInput, setCompetitorInput] = useState<string>('');
  const [keywordsInput, setKeywordsInput] = useState<string>('');
  const [activeProposalId, setActiveProposalId] = useState<string | null>(
    null,
  );

  function handleGenerate() {
    if (!selectedUrl.trim()) return;
    const competitor_urls = competitorInput
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const target_keywords = keywordsInput
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    generate.mutate(
      { our_url: selectedUrl, competitor_urls, target_keywords },
      {
        onSuccess: (data) => setActiveProposalId(data.id),
      },
    );
  }

  return (
    <div className="bajaj-ui p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-brand-text">
          Content Writer
        </h1>
        <p className="mt-1 text-sm text-brand-text-3">
          Generate Bajaj Life Insurance page rewrites grounded in our crawl
          + competitor evidence. Every generated string cites a real source
          — unbacked lines are dropped before you see them.
        </p>
      </header>

      {/* ── Inputs ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>1. Pick a page + evidence</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-brand-text-3">
              Our page
              {ourPages.data && (
                <span className="ml-2 text-brand-text-3">
                  ({ourPages.data.pages.length} crawled URLs available)
                </span>
              )}
            </label>
            <select
              value={selectedUrl}
              onChange={(e) => setSelectedUrl(e.target.value)}
              className="w-full rounded border border-brand-line bg-white p-2 text-sm"
            >
              <option value="">— select a URL —</option>
              {(ourPages.data?.pages || []).map((p) => (
                <option key={p.url} value={p.url}>
                  [{p.page_type || '?'}] {p.url} ({p.word_count}w)
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-brand-text-3">
                Competitor URLs (one per line or comma-separated)
              </label>
              <textarea
                value={competitorInput}
                onChange={(e) => setCompetitorInput(e.target.value)}
                placeholder="https://www.iciciprulife.com/...&#10;https://www.hdfclife.com/..."
                rows={4}
                className="w-full rounded border border-brand-line bg-white p-2 font-mono text-xs"
              />
              <p className="mt-1 text-xs text-brand-text-3">
                URLs must have been captured by a previous gap-pipeline deep
                crawl. Missing URLs are skipped silently.
              </p>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-brand-text-3">
                Target keywords (one per line or comma-separated)
              </label>
              <textarea
                value={keywordsInput}
                onChange={(e) => setKeywordsInput(e.target.value)}
                placeholder="term insurance for women&#10;1 crore term plan&#10;..."
                rows={4}
                className="w-full rounded border border-brand-line bg-white p-2 text-xs"
              />
              <p className="mt-1 text-xs text-brand-text-3">
                Informs the rewrite but is not citable evidence.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button
              onClick={handleGenerate}
              disabled={!selectedUrl || generate.isPending}
            >
              {generate.isPending ? 'Generating…' : 'Generate rewrite'}
            </Button>
            {generate.error && (
              <span className="text-xs text-severity-error">
                {(generate.error as Error).message}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── Proposal diff ──────────────────────────────────────────── */}
      {activeProposalId && (
        <ProposalDiff
          isLoading={generate.isPending}
          proposalId={activeProposalId}
        />
      )}

      {/* ── Recent proposals ──────────────────────────────────────── */}
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
                    className="border-t border-brand-line hover:bg-brand-tint-50"
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Diff component ─────────────────────────────────────────────────


function ProposalDiff({
  proposalId,
  isLoading,
}: {
  proposalId: string;
  isLoading: boolean;
}) {
  const { data } = useContentWriterProposal(proposalId);
  const [showSource, setShowSource] = useState<string | null>(null);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-brand-text-3">
          Generating proposal — typically takes 5-15 seconds…
        </CardContent>
      </Card>
    );
  }
  if (!data) return null;

  if (data.error) {
    return (
      <Card className="border-severity-error">
        <CardContent className="py-4">
          <div className="font-medium text-severity-error">
            Generation failed
          </div>
          <div className="mt-1 text-xs text-brand-text-3">{data.error}</div>
        </CardContent>
      </Card>
    );
  }

  const proposed = data.generated_proposal || {};
  const ev = (data.evidence_dict || {}) as Record<string, unknown>;
  const ourTitle = (ev['our:title'] as string) || '';
  const ourMeta = (ev['our:meta_description'] as string) || '';
  const ourHeadingKeys = Object.keys(ev)
    .filter((k) => k.startsWith('our:headings['))
    .sort(byIdx);
  const ourLinkKeys = Object.keys(ev)
    .filter((k) => k.startsWith('our:internal_links['))
    .sort(byIdx);

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-baseline justify-between">
            <CardTitle>2. Proposed rewrite</CardTitle>
            <div className="text-xs text-brand-text-3">
              <span className="text-severity-success">
                {data.critic_verdict?.accepted ?? 0} backed
              </span>
              {' • '}
              <span
                className={
                  (data.critic_verdict?.rejected ?? 0) > 0
                    ? 'text-severity-warning'
                    : ''
                }
              >
                {data.critic_verdict?.rejected ?? 0} unbacked (dropped)
              </span>
              {' • '}
              <span>${data.cost_usd.toFixed(4)}</span>
              {' • '}
              <span>
                {data.tokens_in + data.tokens_out} tokens
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-6">
            {/* Current */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Current
              </h3>
              <DiffLine label="Title" current={ourTitle} />
              <DiffLine label="Meta" current={ourMeta} multiline />
              <div className="mt-4">
                <div className="text-xs font-semibold text-brand-text-3">
                  Headings ({ourHeadingKeys.length})
                </div>
                <ul className="mt-1 space-y-0.5">
                  {ourHeadingKeys.slice(0, 12).map((k) => {
                    const h = ev[k] as { level: number; text: string };
                    return (
                      <li
                        key={k}
                        className="text-xs"
                        style={{ paddingLeft: (h?.level ?? 1) * 8 }}
                      >
                        <span className="text-brand-text-3">
                          h{h?.level}{' '}
                        </span>
                        {h?.text}
                      </li>
                    );
                  })}
                  {ourHeadingKeys.length > 12 && (
                    <li className="text-xs text-brand-text-3">
                      …{ourHeadingKeys.length - 12} more
                    </li>
                  )}
                </ul>
              </div>
              <div className="mt-4">
                <div className="text-xs font-semibold text-brand-text-3">
                  Internal links ({ourLinkKeys.length})
                </div>
                <ul className="mt-1 space-y-0.5">
                  {ourLinkKeys.slice(0, 8).map((k) => {
                    const l = ev[k] as { anchor: string; href: string };
                    return (
                      <li key={k} className="break-all text-xs">
                        <span className="text-brand-text-3">{l?.anchor || '—'} → </span>
                        <span className="font-mono">{l?.href}</span>
                      </li>
                    );
                  })}
                  {ourLinkKeys.length > 8 && (
                    <li className="text-xs text-brand-text-3">
                      …{ourLinkKeys.length - 8} more
                    </li>
                  )}
                </ul>
              </div>
            </div>

            {/* Proposed */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Proposed
              </h3>
              {proposed.proposed_title && (
                <DiffLine
                  label="Title"
                  current={proposed.proposed_title.text}
                  cited={proposed.proposed_title}
                  onSourceClick={setShowSource}
                />
              )}
              {proposed.proposed_meta_description && (
                <DiffLine
                  label="Meta"
                  current={proposed.proposed_meta_description.text}
                  cited={proposed.proposed_meta_description}
                  onSourceClick={setShowSource}
                  multiline
                />
              )}
              {proposed.proposed_headings &&
                proposed.proposed_headings.length > 0 && (
                  <div className="mt-4">
                    <div className="text-xs font-semibold text-brand-text-3">
                      Headings ({proposed.proposed_headings.length})
                    </div>
                    <ul className="mt-1 space-y-1">
                      {proposed.proposed_headings.map((h, i) => (
                        <li
                          key={i}
                          className="text-xs"
                          style={{ paddingLeft: (h.level ?? 1) * 8 }}
                        >
                          <span className="text-brand-text-3">h{h.level} </span>
                          {h.text}{' '}
                          <SourcePill
                            cited={h}
                            onClick={setShowSource}
                          />
                          {h.rationale && (
                            <div
                              className="mt-0.5 text-[10px] italic text-brand-text-3"
                              style={{ paddingLeft: 8 }}
                            >
                              why: {h.rationale}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              {proposed.proposed_internal_links &&
                proposed.proposed_internal_links.length > 0 && (
                  <div className="mt-4">
                    <div className="text-xs font-semibold text-brand-text-3">
                      Internal links ({proposed.proposed_internal_links.length})
                    </div>
                    <ul className="mt-1 space-y-1">
                      {proposed.proposed_internal_links.map((l, i) => (
                        <li key={i} className="break-all text-xs">
                          <span className="text-brand-text-3">
                            {l.anchor || '—'} →{' '}
                          </span>
                          <span className="font-mono">{l.target_url}</span>{' '}
                          <SourcePill
                            cited={l}
                            onClick={setShowSource}
                          />
                          {l.rationale && (
                            <div className="mt-0.5 text-[10px] italic text-brand-text-3">
                              why: {l.rationale}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              {proposed.overall_rationale && (
                <div className="mt-4 rounded border border-brand-line bg-brand-tint-50 p-2 text-xs">
                  <span className="font-semibold">Strategy: </span>
                  {proposed.overall_rationale}
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Rejected list */}
      {data.critic_verdict?.rejected_items &&
        data.critic_verdict.rejected_items.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Dropped by the critic ({data.critic_verdict.rejected})</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="mb-2 text-xs text-brand-text-3">
                These lines the model tried to emit but could not back with
                evidence. They were dropped before reaching you. Listed here
                so you can audit what the model was tempted to invent.
              </p>
              <ul className="space-y-1 text-xs">
                {data.critic_verdict.rejected_items.map((r, i) => (
                  <li key={i}>
                    <span className="font-mono text-brand-text-3">{r.path}</span>
                    {' — '}
                    <span className="text-severity-warning">{r.reason}</span>
                    {r.source_ref && (
                      <span className="ml-1 text-brand-text-3">
                        (tried: <code>{r.source_ref}</code>)
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

      {/* Source-inspect drawer */}
      {showSource && (
        <Card className="border-brand-accent">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">
                Evidence: <code>{showSource}</code>
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowSource(null)}
              >
                Close
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto whitespace-pre-wrap text-xs">
              {JSON.stringify(ev[showSource], null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </>
  );
}

// ── helpers ────────────────────────────────────────────────────────


function byIdx(a: string, b: string): number {
  const ai = Number(a.match(/\[(\d+)\]/)?.[1] ?? 0);
  const bi = Number(b.match(/\[(\d+)\]/)?.[1] ?? 0);
  return ai - bi;
}


function SourcePill({
  cited,
  onClick,
}: {
  cited: CitedString | CitedHeading | CitedLink;
  onClick: (ref: string) => void;
}) {
  if (!cited?.source_ref) return null;
  return (
    <button
      type="button"
      onClick={() => onClick(cited.source_ref)}
      className="ml-1 inline-flex items-center rounded border border-brand-accent bg-brand-tint-50 px-1.5 py-0 text-[10px] font-mono text-brand-accent hover:bg-brand-accent hover:text-white"
      title="Click to inspect source evidence"
    >
      {cited.source_ref}
    </button>
  );
}


function DiffLine({
  label,
  current,
  cited,
  onSourceClick,
  multiline,
}: {
  label: string;
  current: string;
  cited?: CitedString;
  onSourceClick?: (ref: string) => void;
  multiline?: boolean;
}) {
  return (
    <div className="mb-3">
      <div className="text-[10px] uppercase tracking-wide text-brand-text-3">
        {label}
      </div>
      <div
        className={
          multiline
            ? 'mt-0.5 whitespace-pre-wrap text-sm'
            : 'mt-0.5 text-sm font-medium'
        }
      >
        {current || (
          <span className="italic text-brand-text-3">— empty —</span>
        )}
        {cited && onSourceClick && (
          <SourcePill cited={cited} onClick={onSourceClick} />
        )}
      </div>
    </div>
  );
}
