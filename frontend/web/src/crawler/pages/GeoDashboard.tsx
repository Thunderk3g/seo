/**
 * GeoDashboard — `/geo`.
 *
 * Phase 6 final UI. Four tiles on a single Ahrefs-style overview:
 *   1. llms.txt status card — presence, byte size, sections, issues +
 *      a "Generate draft" button that opens the proposed body.
 *   2. AI-bot crawl heatmap — per-bot verified vs spoofed counts.
 *   3. IndexNow ping panel — paste URLs, push to Bing + Yandex.
 *   4. Backlink summary — Common Crawl top referring domains.
 *
 * Pure shadcn + Bajaj brand. No emojis, no chart library — SVG bars
 * mirror the lattice.css conventions used everywhere else.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { crawlerApi } from '../api';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';

export default function GeoDashboard() {
  return (
    <div className="bajaj-ui p-6 space-y-4">
      <header className="mb-2">
        <h1 className="text-2xl font-semibold text-brand-text">GEO suite</h1>
        <p className="mt-1 text-sm text-brand-text-3">
          AI-search readiness — llms.txt, AI-bot crawl activity,
          IndexNow pings, and Common Crawl backlinks. All four signals
          industry SEO tools don't cover.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LlmsTxtCard />
        <AiBotHitsCard />
        <IndexNowCard />
        <BacklinksCard />
      </div>
    </div>
  );
}

// ── llms.txt ──────────────────────────────────────────────────────────────

function LlmsTxtCard() {
  const [showDraft, setShowDraft] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['geo', 'llms-txt'],
    queryFn: () => crawlerApi.llmsTxtAudit(),
    staleTime: 5 * 60_000,
  });
  const draftQuery = useQuery({
    queryKey: ['geo', 'llms-txt', 'draft'],
    queryFn: () => crawlerApi.llmsTxtDraft(30),
    enabled: showDraft,
    staleTime: 5 * 60_000,
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <CardTitle className="text-base">llms.txt</CardTitle>
          {data && (
            <Badge variant={data.found ? 'success' : 'error'}>
              {data.found ? `Live (${data.byte_size.toLocaleString()} B)` : `Missing (HTTP ${data.status_code})`}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && <div className="text-sm text-brand-text-3">Fetching /llms.txt…</div>}

        {data && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-3 gap-2 text-center">
              <Stat label="Sections" value={data.section_count} />
              <Stat label="Links" value={data.link_count} />
              <Stat label="llms-full.txt" value={data.has_full_txt ? 'Yes' : 'No'} />
            </div>

            {data.issues.length > 0 && (
              <ul className="space-y-1 rounded border border-severity-warning/30 bg-severity-warning/5 p-2 text-xs text-brand-text-2">
                {data.issues.slice(0, 4).map((iss) => (
                  <li key={iss}>{iss}</li>
                ))}
              </ul>
            )}

            <div className="flex items-center gap-2">
              <Button size="sm" onClick={() => setShowDraft((v) => !v)}>
                {showDraft ? 'Hide draft' : 'Generate draft'}
              </Button>
              {showDraft && draftQuery.data && (
                <span className="text-xs text-brand-text-3">
                  {draftQuery.data.section_count} sections · {draftQuery.data.page_count} pages · {draftQuery.data.char_count.toLocaleString()} chars
                </span>
              )}
            </div>

            {showDraft && draftQuery.isLoading && (
              <div className="text-xs text-brand-text-3">Building draft from AEM…</div>
            )}
            {showDraft && draftQuery.data && (
              <pre className="max-h-72 overflow-auto rounded border border-brand-border bg-brand-surface-2 p-3 text-xs text-brand-text">
                {draftQuery.data.body}
              </pre>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded border border-brand-border bg-brand-surface-2 p-2">
      <div className="text-xs text-brand-text-3">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-brand-text">{value}</div>
    </div>
  );
}

// ── AI-bot hits ──────────────────────────────────────────────────────────

function AiBotHitsCard() {
  const { data, isLoading } = useQuery({
    queryKey: ['geo', 'ai-bots'],
    queryFn: () => crawlerApi.aiBotHits(50),
    staleTime: 5 * 60_000,
  });

  const totals = data?.totals ?? {};
  const totalRows = Object.entries(totals).sort((a, b) => b[1].total - a[1].total);
  const grandTotal = totalRows.reduce((s, [, v]) => s + v.total, 0);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">AI-bot crawl activity</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <div className="text-sm text-brand-text-3">Loading bot logs…</div>}

        {data && totalRows.length === 0 && (
          <div className="text-sm text-brand-text-3">
            No verified AI-bot hits yet.
            <div className="mt-1 text-xs">
              Drop combined-format CDN logs into <code className="font-mono">data/logs/</code> and run
              <code className="ml-1 font-mono">python manage.py ingest_bot_logs</code>.
            </div>
          </div>
        )}

        {data && totalRows.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-brand-text-3">
              {grandTotal.toLocaleString()} total hits across {totalRows.length} bots
            </div>
            <table className="w-full text-sm">
              <thead className="border-b border-brand-border text-left">
                <tr>
                  <th className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">Bot</th>
                  <th className="px-2 py-1 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Total</th>
                  <th className="px-2 py-1 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Verified</th>
                  <th className="px-2 py-1 text-right text-xs font-semibold uppercase tracking-wide text-brand-text-3">Spoofed</th>
                </tr>
              </thead>
              <tbody>
                {totalRows.map(([bot, counts]) => (
                  <tr key={bot} className="border-t border-brand-border">
                    <td className="px-2 py-1 text-brand-text">{bot}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{counts.total.toLocaleString()}</td>
                    <td className="px-2 py-1 text-right tabular-nums text-severity-success">{counts.verified.toLocaleString()}</td>
                    <td className="px-2 py-1 text-right tabular-nums text-severity-error">{counts.spoofed.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── IndexNow ─────────────────────────────────────────────────────────────

function IndexNowCard() {
  const [urls, setUrls] = useState('');
  const qc = useQueryClient();
  const mut = useMutation({
    mutationFn: (urlList: string[]) => crawlerApi.indexNowPing(urlList),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['geo'] }),
  });

  const lineCount = urls.split(/\r?\n/).filter((l) => l.trim()).length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">IndexNow ping</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-brand-text-3">
          One ping reaches Bing, Yandex, Naver, Seznam. Allow-list
          rejects anything outside Bajaj domains. Dry-run unless the
          INDEXNOW_KEY env var is set.
        </p>
        <textarea
          className="h-28 w-full rounded border border-brand-border bg-brand-surface-2 p-2 font-mono text-xs text-brand-text"
          placeholder={'https://www.bajajlifeinsurance.com/\nhttps://www.bajajlifeinsurance.com/term-insurance/'}
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
        />
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            disabled={lineCount === 0 || mut.isPending}
            onClick={() => {
              const list = urls.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
              if (list.length) mut.mutate(list);
            }}
          >
            {mut.isPending ? 'Sending…' : `Ping ${lineCount} URL${lineCount === 1 ? '' : 's'}`}
          </Button>
          {mut.data && (
            <span className="text-xs">
              {mut.data.ok ? (
                <span className="text-severity-success">
                  {mut.data.dry_run
                    ? `Dry run · would submit ${mut.data.would_submit ?? 0}`
                    : `Sent ${mut.data.submitted ?? 0} · HTTP ${mut.data.status_code ?? '—'}`}
                </span>
              ) : (
                <span className="text-severity-error">{mut.data.error || 'Failed'}</span>
              )}
              {(mut.data.rejected_count ?? 0) > 0 && (
                <span className="ml-2 text-brand-text-3">
                  ({mut.data.rejected_count} rejected by allow-list)
                </span>
              )}
            </span>
          )}
        </div>
        {mut.data?.note && (
          <div className="rounded border border-brand-border bg-brand-surface-2 p-2 text-xs text-brand-text-3">
            {mut.data.note}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Backlinks ────────────────────────────────────────────────────────────

function BacklinksCard() {
  const { data, isLoading } = useQuery({
    queryKey: ['geo', 'backlinks'],
    queryFn: () => crawlerApi.backlinks(20),
    staleTime: 5 * 60_000,
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <CardTitle className="text-base">Backlinks (Common Crawl)</CardTitle>
          {data && (
            <Badge variant={data.summary.total > 0 ? 'success' : 'notice'}>
              {data.summary.total.toLocaleString()} edges
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && <div className="text-sm text-brand-text-3">Loading backlinks…</div>}

        {data && data.summary.total === 0 && (
          <div className="text-sm text-brand-text-3">
            No backlinks loaded yet.
            <div className="mt-1 text-xs">
              Drop a seed at <code className="font-mono">data/backlinks_seed.csv</code> and run
              <code className="ml-1 font-mono">python manage.py pull_commoncrawl_backlinks</code>.
              The live WAT pipeline lands next sprint.
            </div>
          </div>
        )}

        {data && data.summary.total > 0 && (
          <div className="space-y-3">
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Top referring domains
              </div>
              <ul className="text-sm">
                {data.summary.top_referring_domains.slice(0, 6).map((d) => (
                  <li key={d.source_domain} className="flex items-center justify-between border-t border-brand-border py-1">
                    <span className="text-brand-text">{d.source_domain || '(unknown)'}</span>
                    <span className="tabular-nums text-brand-text-3">{d.count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Most recent
              </div>
              <ul className="space-y-1 text-xs">
                {data.backlinks.slice(0, 5).map((b) => (
                  <li key={b.id} className="border-t border-brand-border py-1">
                    <div className="truncate text-brand-text-2">{b.source_url}</div>
                    <div className="truncate text-brand-text-3">
                      → {b.target_url} {b.nofollow && <span className="ml-1 italic">(nofollow)</span>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
