/**
 * CompetitorDetailPage — `/competitors/<domain>/`.
 *
 * Replaces the DeepCrawlPanel "dropdown" view. Shows the per-competitor
 * KPI summary at the top, then a proper table of sample pages. Each
 * row links to the per-URL detail page (opens in new tab) so the
 * operator can read formatted content without leaving context.
 *
 * Bajaj brand via shadcn primitives; scoped under `.bajaj-ui`.
 */
import { useMemo, useState } from 'react';
import { Link, useParams } from 'wouter';
import { useCompetitorDetail } from '../api/hooks/useCompetitorDetail';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import CompetitorMetaAdsSection from '../components/competitors/CompetitorMetaAdsSection';
import CompetitorContentMapSection from '../components/competitors/CompetitorContentMapSection';
import CompetitorContentClusterSection from '../components/competitors/CompetitorContentClusterSection';
import CompetitorKeywordsSection from '../components/competitors/CompetitorKeywordsSection';

export default function CompetitorDetailPage() {
  const params = useParams<{ domain: string }>();
  const domain = params.domain ? decodeURIComponent(params.domain) : null;
  const { data, isLoading, isError, error } = useCompetitorDetail(domain);

  const tracked = data?.profile_summary;

  const cwvBadge = useMemo(() => {
    if (!tracked?.avg_pagespeed_score) return null;
    const s = Math.round(tracked.avg_pagespeed_score);
    if (s >= 90) return { variant: 'success' as const, label: `PageSpeed ${s}` };
    if (s >= 50) return { variant: 'warning' as const, label: `PageSpeed ${s}` };
    return { variant: 'error' as const, label: `PageSpeed ${s}` };
  }, [tracked?.avg_pagespeed_score]);

  if (isLoading) {
    return (
      <div className="bajaj-ui p-6 text-sm text-brand-text-3">
        Loading competitor detail…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bajaj-ui p-6">
        <Card className="border-severity-error">
          <CardContent className="py-4">
            <div className="text-severity-error">
              {error instanceof Error ? error.message : 'Failed to load competitor'}
            </div>
            <Link href="/competitors">
              <Button variant="outline" size="sm" className="mt-3">
                Back to competitors
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="text-xs text-brand-text-3">
            <Link href="/competitors">
              <span className="cursor-pointer hover:underline">Competitors</span>
            </Link>
            <span className="mx-2">/</span>
            <span>{data.domain}</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-brand-text">
            {data.domain}
            {data.is_us && (
              <Badge variant="default" className="ml-3 align-middle">us</Badge>
            )}
          </h1>
          <p className="mt-1 text-sm text-brand-text-3">
            {data.pages_ok}/{data.pages_attempted} pages crawled from a sitemap of{' '}
            {data.sitemap_url_count.toLocaleString()} URLs
            {data.run_started_at && (
              <>
                {' '}· snapshot {new Date(data.run_started_at).toLocaleDateString()}
              </>
            )}
          </p>
        </div>
        <a
          href={`https://${data.domain}/`}
          target="_blank"
          rel="noreferrer"
        >
          <Button variant="outline" size="sm">Visit site</Button>
        </a>
      </header>

      {tracked && <ProfileSummaryGrid summary={tracked} cwvBadge={cwvBadge} />}

      <section className="mt-6">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-brand-text">
            Sample pages
          </h2>
          <span className="text-xs text-brand-text-3">
            {data.sample_count} captured
          </span>
        </div>
        <SamplePagesTable
          domain={data.domain}
          pages={data.sample_pages}
        />
      </section>

      {/* Phase 7 — keyword intelligence. Two tabs: Semrush ranking
          keywords (authoritative, cached on disk) and in-house TF-IDF
          content keywords (what they write about, free). Positioned
          above the maps because "what do they target" reads top-down
          better than seeing the structure first. */}
      <CompetitorKeywordsSection domain={data.domain} />

      {/* Per-competitor content map — own PageEmbedding rows + UMAP
          projection, isolated from Bajaj's map. Renders page-type +
          product breakdown derived from the embedded pages. */}
      <CompetitorContentMapSection domain={data.domain} />

      {/* Per-competitor content CLUSTER tree — rule-based, no embeddings
          needed, so it renders straight after a crawl even when the 3D
          map above is still empty (refresh_content_map hasn't run for
          this domain yet). Diagram + text views of Product → Page-type
          → URLs. Shares the same /content/clusters endpoint as ours,
          scoped via ?domain=. */}
      <CompetitorContentClusterSection domain={data.domain} />

      {/* Meta Ad Library — competitor ad intel via Apify scraper. Caches
          on the backend for 24h so this doesn't burn Apify credit on
          every render. */}
      <CompetitorMetaAdsSection
        competitor={data.domain}
        displayName={data.domain}
      />
    </div>
  );
}

function ProfileSummaryGrid({
  summary,
  cwvBadge,
}: {
  summary: NonNullable<ReturnType<typeof useCompetitorDetail>['data']>['profile_summary'];
  cwvBadge: { variant: 'success' | 'warning' | 'error'; label: string } | null;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Profile summary</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Avg word count" value={summary.avg_word_count.toLocaleString()} />
          <Stat label="Schema coverage" value={`${summary.schema_pct}%`} />
          <Stat label="Avg response" value={`${summary.avg_response_ms} ms`} />
          <Stat label="AI citability" value={summary.ai_citability_score.toFixed(0)} />
          <Stat label="H1 coverage" value={`${summary.h1_pct}%`} />
          <Stat
            label="Pages with CWV"
            value={summary.cwv_pages_count.toLocaleString()}
          />
          <Stat
            label="Median LCP"
            value={summary.median_lcp_ms ? `${summary.median_lcp_ms} ms` : '—'}
          />
          <Stat
            label="Median CLS"
            value={summary.median_cls ? summary.median_cls.toFixed(3) : '—'}
          />
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {cwvBadge && <Badge variant={cwvBadge.variant}>{cwvBadge.label}</Badge>}
          {summary.has_pricing_page && <Badge variant="notice">/pricing</Badge>}
          {summary.has_llms_txt && <Badge variant="success">llms.txt</Badge>}
          {summary.has_pricing_md && <Badge variant="notice">pricing.md</Badge>}
        </div>

        {summary.schema_types.length > 0 && (
          <div className="mt-5">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              Schema types detected
            </div>
            <div className="flex flex-wrap gap-1.5">
              {summary.schema_types.map((t) => (
                <Badge key={t} variant="outline">{t}</Badge>
              ))}
            </div>
          </div>
        )}

        {Object.keys(summary.page_types).length > 0 && (
          <div className="mt-5">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              Page-type breakdown
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(summary.page_types)
                .filter(([, n]) => n > 0)
                .map(([t, n]) => (
                  <Badge key={t} variant="outline">
                    {t} {n}
                  </Badge>
                ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-brand-text-3">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-brand-text">{value}</div>
    </div>
  );
}

function SamplePagesTable({
  domain,
  pages,
}: {
  domain: string;
  pages: Array<{
    url: string;
    url_b64: string;
    title: string;
    page_type: string;
    word_count: number;
    has_schema: boolean;
    pagespeed_score: number | null;
    lcp_ms: number | null;
    response_time_ms: number;
  }>;
}) {
  // Client-side pagination — competitors with 3000+ pages would render
  // as one giant scrolling table otherwise. 250 rows per page is the
  // sweet spot: enough to scan a product section in one chunk, small
  // enough that the DOM stays fast on slow machines.
  const [pageSize, setPageSize] = useState(250);
  const [pageIdx, setPageIdx] = useState(0);
  const totalPages = Math.max(1, Math.ceil(pages.length / pageSize));
  const safePageIdx = Math.min(pageIdx, totalPages - 1);
  const start = safePageIdx * pageSize;
  const visiblePages = pages.slice(start, start + pageSize);

  if (pages.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-sm text-brand-text-3">
          No sample pages captured for this competitor.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="overflow-hidden rounded-md border border-brand-border bg-card shadow-e1">
      {pages.length > pageSize && (
        <PageControls
          pageIdx={safePageIdx}
          totalPages={totalPages}
          pageSize={pageSize}
          totalRows={pages.length}
          rangeStart={start + 1}
          rangeEnd={Math.min(start + pageSize, pages.length)}
          onPrev={() => setPageIdx((p) => Math.max(0, p - 1))}
          onNext={() => setPageIdx((p) => Math.min(totalPages - 1, p + 1))}
          onJump={(i) => setPageIdx(i)}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPageIdx(0);
          }}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-brand-border bg-brand-surface-2 text-left">
            <tr>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Title
              </th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Page type
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Words
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Schema
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                PageSpeed
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                LCP (ms)
              </th>
              <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Response (ms)
              </th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3" />
            </tr>
          </thead>
          <tbody>
            {visiblePages.map((page, idx) => {
              const target = `/competitors/${encodeURIComponent(domain)}/pages/${page.url_b64}`;
              return (
                <tr
                  key={page.url_b64}
                  className={`border-t border-brand-border align-top hover:bg-brand-accent-soft ${idx % 2 === 1 ? 'bg-brand-surface-2/50' : ''}`}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-brand-text">
                      {page.title || <span className="text-brand-text-3 italic">— no title —</span>}
                    </div>
                    <div className="mt-0.5 break-all font-mono text-xs text-brand-text-3">
                      {page.url}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-brand-text-2">{page.page_type || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {page.word_count.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {page.has_schema ? (
                      <Badge variant="success">yes</Badge>
                    ) : (
                      <Badge variant="outline">no</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {page.pagespeed_score !== null && page.pagespeed_score !== undefined
                      ? page.pagespeed_score
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {page.lcp_ms !== null && page.lcp_ms !== undefined
                      ? page.lcp_ms.toLocaleString()
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {page.response_time_ms.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <a href={target} target="_blank" rel="noreferrer">
                      <Button variant="outline" size="sm">
                        Open
                      </Button>
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pages.length > pageSize && (
        <PageControls
          pageIdx={safePageIdx}
          totalPages={totalPages}
          pageSize={pageSize}
          totalRows={pages.length}
          rangeStart={start + 1}
          rangeEnd={Math.min(start + pageSize, pages.length)}
          onPrev={() => setPageIdx((p) => Math.max(0, p - 1))}
          onNext={() => setPageIdx((p) => Math.min(totalPages - 1, p + 1))}
          onJump={(i) => setPageIdx(i)}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPageIdx(0);
          }}
        />
      )}
    </div>
  );
}

function PageControls({
  pageIdx,
  totalPages,
  pageSize,
  totalRows,
  rangeStart,
  rangeEnd,
  onPrev,
  onNext,
  onJump,
  onPageSizeChange,
}: {
  pageIdx: number;
  totalPages: number;
  pageSize: number;
  totalRows: number;
  rangeStart: number;
  rangeEnd: number;
  onPrev: () => void;
  onNext: () => void;
  onJump: (i: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  // Show first / last / pageIdx-1 / pageIdx / pageIdx+1 with ellipses.
  const pageNumbers: (number | 'ellipsis-left' | 'ellipsis-right')[] = [];
  if (totalPages <= 7) {
    for (let i = 0; i < totalPages; i++) pageNumbers.push(i);
  } else {
    pageNumbers.push(0);
    if (pageIdx > 2) pageNumbers.push('ellipsis-left');
    const mid = [pageIdx - 1, pageIdx, pageIdx + 1].filter(
      (i) => i > 0 && i < totalPages - 1,
    );
    for (const m of mid) pageNumbers.push(m);
    if (pageIdx < totalPages - 3) pageNumbers.push('ellipsis-right');
    pageNumbers.push(totalPages - 1);
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-border bg-brand-surface-2 px-3 py-2 text-xs last:border-b-0 last:border-t">
      <div className="text-brand-text-3">
        Showing <span className="font-semibold text-brand-text">{rangeStart}</span>
        –<span className="font-semibold text-brand-text">{rangeEnd}</span> of{' '}
        <span className="font-semibold text-brand-text">{totalRows.toLocaleString()}</span> pages
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-brand-text-3">
          Rows
          <select
            value={pageSize}
            onChange={(e) => onPageSizeChange(parseInt(e.target.value, 10))}
            className="rounded border border-brand-border bg-white px-1.5 py-0.5 text-brand-text"
          >
            <option value={100}>100</option>
            <option value={250}>250</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </label>
        <button
          type="button"
          onClick={onPrev}
          disabled={pageIdx === 0}
          className="rounded border border-brand-border bg-white px-2 py-1 text-brand-text disabled:cursor-not-allowed disabled:opacity-40"
        >
          ← Prev
        </button>
        <div className="flex items-center gap-1">
          {pageNumbers.map((n, i) =>
            typeof n === 'string' ? (
              <span key={`${n}-${i}`} className="text-brand-text-3">
                …
              </span>
            ) : (
              <button
                key={n}
                type="button"
                onClick={() => onJump(n)}
                className={
                  n === pageIdx
                    ? 'rounded bg-brand-accent px-2 py-1 font-semibold text-white'
                    : 'rounded border border-brand-border bg-white px-2 py-1 text-brand-text hover:bg-brand-accent-soft'
                }
              >
                {n + 1}
              </button>
            ),
          )}
        </div>
        <button
          type="button"
          onClick={onNext}
          disabled={pageIdx >= totalPages - 1}
          className="rounded border border-brand-border bg-white px-2 py-1 text-brand-text disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
