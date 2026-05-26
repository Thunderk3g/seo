/**
 * CustodiansPage — `/custodians`.
 *
 * Operator-facing snapshot of the agent fleet's data layer:
 * OurDataCustodian (bajajlifeinsurance.com) side-by-side with each
 * TheirDataCustodian (one row per roster competitor), plus the
 * SiteDiffer report of structural gaps.
 *
 * No LLM — pure data. The page is the visible counterpart to the
 * Celery beat job that re-crawls competitors at 03:00 IST: this is
 * "what we currently know" about every domain. Empty rows for a
 * competitor mean the link-walking spider hasn't run yet.
 */
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import {
  useCustodiansSummary,
  type DomainSummary,
} from '../api/hooks/useCustodians';
import { useLayout, useStructureGaps } from '../api/hooks/useBriefings';

export default function CustodiansPage() {
  const { data, isLoading, isError, error } = useCustodiansSummary();
  const layoutQ = useLayout();
  const structureQ = useStructureGaps(50);

  if (isLoading) {
    return (
      <div className="bajaj-ui p-6 text-sm text-brand-text-3">
        Loading custodian summary…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="bajaj-ui p-6">
        <Card className="border-severity-error">
          <CardContent className="py-4 text-severity-error">
            {error instanceof Error ? error.message : 'Failed to load summary'}
          </CardContent>
        </Card>
      </div>
    );
  }

  const { our, competitors, diff } = data;

  return (
    <div className="bajaj-ui p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-brand-text">
          Data Custodians
        </h1>
        <p className="mt-1 text-sm text-brand-text-3">
          One row per domain. OurDataCustodian owns Bajaj data; every
          TheirDataCustodian owns one competitor. Empty competitor rows
          mean the daily walk hasn’t populated that domain yet.
        </p>
      </header>

      {/* ── Our custodian ────────────────────────────────────────── */}
      <CustodianCard summary={our} />

      {/* ── Their custodians ─────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>
            Competitor custodians ({competitors.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-xs">
            <thead className="text-brand-text-3">
              <tr>
                <th className="px-2 py-1 text-left">Domain</th>
                <th className="px-2 py-1 text-right">Pages</th>
                <th className="px-2 py-1 text-right">Med. words</th>
                <th className="px-2 py-1 text-right">Schema %</th>
                <th className="px-2 py-1 text-right">PSI</th>
                <th className="px-2 py-1 text-right">LCP ms</th>
                <th className="px-2 py-1 text-left">Changes (7d)</th>
                <th className="px-2 py-1 text-left">Snapshot</th>
              </tr>
            </thead>
            <tbody>
              {competitors.map((t) => (
                <tr
                  key={t.domain}
                  className="border-t border-brand-line hover:bg-brand-tint-50"
                >
                  <td className="px-2 py-1 font-medium">{t.domain}</td>
                  <td className="px-2 py-1 text-right">
                    {t.ok_page_count > 0 ? (
                      t.ok_page_count
                    ) : (
                      <span className="text-brand-text-3">—</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-right">{t.median_word_count || '—'}</td>
                  <td className="px-2 py-1 text-right">{t.has_schema_pct || '—'}</td>
                  <td className="px-2 py-1 text-right">{t.avg_pagespeed_score ?? '—'}</td>
                  <td className="px-2 py-1 text-right">{t.median_lcp_ms ?? '—'}</td>
                  <td className="px-2 py-1">
                    {Object.keys(t.recent_changes).length > 0 ? (
                      <ChangeBadges changes={t.recent_changes} />
                    ) : (
                      <span className="text-brand-text-3">none</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-brand-text-3">
                    {t.snapshot_date
                      ? new Date(t.snapshot_date).toLocaleDateString()
                      : <span className="italic">no crawl yet</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* ── SiteDiffer report ───────────────────────────────────── */}
      {diff && (
        <Card>
          <CardHeader>
            <CardTitle>SiteDiffer — structural gaps</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-6">
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                  Schema types only on competitors
                </h3>
                <ul className="space-y-1 text-xs">
                  {Object.entries(diff.schema_only_theirs).map(([dom, types]) => (
                    <li key={dom}>
                      <span className="font-medium">{dom}: </span>
                      {types.length > 0 ? (
                        types.map((t) => (
                          <Badge key={t} variant="notice" className="mr-1">
                            {t}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-brand-text-3">none</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                  Internal-link kinds only on competitors
                </h3>
                <ul className="space-y-1 text-xs">
                  {Object.entries(diff.link_kind_gaps).map(([dom, kinds]) => (
                    <li key={dom}>
                      <span className="font-medium">{dom}: </span>
                      {kinds.length > 0 ? (
                        kinds.map((k) => (
                          <Badge key={k} variant="notice" className="mr-1">
                            {k}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-brand-text-3">none</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="mt-4">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                CWV deltas (ours vs theirs — negative = we’re slower)
              </h3>
              <table className="w-full text-xs">
                <thead className="text-brand-text-3">
                  <tr>
                    <th className="px-2 py-1 text-left">Domain</th>
                    <th className="px-2 py-1 text-right">PSI Δ</th>
                    <th className="px-2 py-1 text-right">LCP Δ ms</th>
                    <th className="px-2 py-1 text-right">CLS Δ</th>
                    <th className="px-2 py-1 text-right">INP Δ ms</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(diff.cwv_deltas).map(([dom, metrics]) => (
                    <tr
                      key={dom}
                      className="border-t border-brand-line"
                    >
                      <td className="px-2 py-1">{dom}</td>
                      <td className="px-2 py-1 text-right">{fmt(metrics.pagespeed?.diff)}</td>
                      <td className="px-2 py-1 text-right">{fmt(metrics.lcp_ms?.diff)}</td>
                      <td className="px-2 py-1 text-right">{fmt(metrics.cls?.diff)}</td>
                      <td className="px-2 py-1 text-right">{fmt(metrics.inp_ms?.diff)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── StructureAgent gaps ─────────────────────────────────── */}
      {structureQ.data && (
        <Card>
          <CardHeader>
            <CardTitle>
              StructureAgent — internal-link patterns competitors run that we don't
              {structureQ.data.competitor_snapshot_count > 0 && (
                <span className="ml-2 text-xs font-normal text-brand-text-3">
                  ({structureQ.data.competitor_snapshot_count} competitor
                  snapshot(s); threshold ≥ {structureQ.data.min_pct}%)
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {structureQ.data.competitor_snapshot_count === 0 ? (
              <div className="text-sm text-brand-text-3 italic">
                No competitor snapshots yet — run a walk via{' '}
                <code className="rounded bg-brand-tint-50 px-1">
                  walk_competitor_task.delay('hdfclife.com')
                </code>{' '}
                to populate.
              </div>
            ) : structureQ.data.gaps.length === 0 ? (
              <div className="text-sm text-severity-success">
                No structure gaps detected at the {structureQ.data.min_pct}%
                coverage threshold.
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-brand-text-3">
                  <tr>
                    <th className="px-2 py-1 text-left">On page type</th>
                    <th className="px-2 py-1 text-left">Link kind</th>
                    <th className="px-2 py-1 text-right">Our coverage</th>
                    <th className="px-2 py-1 text-right">Best competitor</th>
                    <th className="px-2 py-1 text-right">Domains</th>
                  </tr>
                </thead>
                <tbody>
                  {structureQ.data.gaps.slice(0, 20).map((g, i) => (
                    <tr
                      key={`${g.source_page_type}-${g.target_kind}-${i}`}
                      className="border-t border-brand-line"
                    >
                      <td className="px-2 py-1 font-mono">{g.source_page_type}</td>
                      <td className="px-2 py-1 font-mono">{g.target_kind}</td>
                      <td className="px-2 py-1 text-right">
                        {g.our_pct.toFixed(1)}%
                      </td>
                      <td className="px-2 py-1 text-right font-semibold text-severity-warning">
                        {g.max_their_pct.toFixed(1)}%
                      </td>
                      <td className="px-2 py-1 text-right">
                        {g.domains_with_pattern}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── LayoutAgent — per-zone link kind diff ───────────────── */}
      {layoutQ.data && (
        <Card>
          <CardHeader>
            <CardTitle>
              LayoutAgent — zone-level differences
              {layoutQ.data.competitor_snapshot_count > 0 && (
                <span className="ml-2 text-xs font-normal text-brand-text-3">
                  ({layoutQ.data.competitor_snapshot_count} competitor
                  snapshot(s))
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {/* Our per-zone rollup */}
            <div className="mb-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Our pages by zone
              </div>
              <table className="w-full text-xs">
                <thead className="text-brand-text-3">
                  <tr>
                    <th className="px-2 py-1 text-left">Zone</th>
                    <th className="px-2 py-1 text-right">Links</th>
                    <th className="px-2 py-1 text-right">Headings</th>
                    <th className="px-2 py-1 text-right">Images</th>
                    <th className="px-2 py-1 text-right">Alt %</th>
                    <th className="px-2 py-1 text-left">Top link kinds</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(layoutQ.data.layout?.zones || {}).map(
                    ([zone, r]) => (
                      <tr key={zone} className="border-t border-brand-line">
                        <td className="px-2 py-1 font-medium">{zone}</td>
                        <td className="px-2 py-1 text-right">{r.link_count}</td>
                        <td className="px-2 py-1 text-right">{r.heading_count}</td>
                        <td className="px-2 py-1 text-right">{r.image_count}</td>
                        <td className="px-2 py-1 text-right">{r.image_alt_pct}</td>
                        <td className="px-2 py-1">
                          {(r.top_link_kinds || []).slice(0, 4).map(([k, n]) => (
                            <Badge key={k} variant="notice" className="mr-1">
                              {k}:{n}
                            </Badge>
                          ))}
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
              {Object.keys(layoutQ.data.layout?.zones || {}).length === 0 && (
                <div className="text-xs text-brand-text-3 italic">
                  No zone data yet — re-crawl Bajaj (the new
                  zone-tagging parser landed Phase H).
                </div>
              )}
            </div>

            {/* Cross-competitor diff */}
            {Object.keys(layoutQ.data.diff?.diffs_by_competitor || {}).length > 0 && (
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                  Link kinds that appear in competitors' zones but not ours
                </div>
                <ul className="space-y-1 text-xs">
                  {Object.entries(
                    layoutQ.data.diff?.diffs_by_competitor || {},
                  ).map(([dom, zoneDiffs]) => (
                    <li key={dom}>
                      <span className="font-medium">{dom}: </span>
                      {zoneDiffs.length === 0 ? (
                        <span className="text-brand-text-3">none</span>
                      ) : (
                        zoneDiffs.map((zd, i) => (
                          <span key={i} className="mr-2">
                            <span className="text-brand-text-3">
                              {zd.zone}:
                            </span>{' '}
                            {zd.kinds_only_in_competitor.map((k) => (
                              <Badge
                                key={k}
                                variant="notice"
                                className="mr-1"
                              >
                                {k}
                              </Badge>
                            ))}
                          </span>
                        ))
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function CustodianCard({ summary }: { summary: DomainSummary }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          OurDataCustodian — <span className="font-mono text-brand-accent">{summary.domain}</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <Stat label="Pages crawled" value={String(summary.page_count)} />
          <Stat label="200 OK" value={String(summary.ok_page_count)} />
          <Stat label="Median word count" value={String(summary.median_word_count)} />
          <Stat label="Schema %" value={`${summary.has_schema_pct}%`} />
          <Stat label="Avg PSI (mobile)" value={String(summary.avg_pagespeed_score ?? '—')} />
          <Stat label="Median LCP" value={summary.median_lcp_ms ? `${summary.median_lcp_ms} ms` : '—'} />
          <Stat label="Median CLS" value={summary.median_cls != null ? summary.median_cls.toFixed(3) : '—'} />
          <Stat label="Median INP" value={summary.median_inp_ms ? `${summary.median_inp_ms} ms` : '—'} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-6">
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              Page types
            </h3>
            <ul className="space-y-0.5 text-xs">
              {Object.entries(summary.page_types || {}).slice(0, 10).map(([k, v]) => (
                <li key={k}>
                  <span className="text-brand-text-3">{k}: </span>
                  {v}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              Top internal-link kinds
            </h3>
            <ul className="space-y-0.5 text-xs">
              {(summary.top_internal_link_kinds || []).slice(0, 10).map(([k, v]) => (
                <li key={k}>
                  <span className="text-brand-text-3">{k}: </span>
                  {v}
                </li>
              ))}
              {(summary.top_internal_link_kinds || []).length === 0 && (
                <li className="text-brand-text-3 italic">
                  none — re-crawl with structural extraction enabled
                </li>
              )}
            </ul>
          </div>
        </div>
        {summary.snapshot_date && (
          <div className="mt-3 text-xs text-brand-text-3">
            Snapshot {summary.snapshot_id?.slice(0, 8)} from{' '}
            {new Date(summary.snapshot_date).toLocaleString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-brand-text-3">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

function ChangeBadges({ changes }: { changes: Record<string, number> }) {
  return (
    <>
      {Object.entries(changes).map(([k, n]) => (
        <Badge key={k} variant="notice" className="mr-1">
          {k}:{n}
        </Badge>
      ))}
    </>
  );
}

function fmt(v: number | null | undefined): string {
  if (v == null) return '—';
  if (Math.abs(v) < 0.01 && v !== 0) return v.toFixed(3);
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}
