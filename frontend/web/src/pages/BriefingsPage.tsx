/**
 * BriefingsPage — `/briefings`.
 *
 * "This week's focus" surface. Renders the Orchestrator V2 `headline`
 * block as a single dashboard — competitor changes in the last 7 days,
 * gap counts, CWV-laggards, biggest change signals — alongside Adobe
 * traffic top pages and the page-level OurDataCustodian summary.
 *
 * The page is purely read-only. Click any change signal to open the
 * competitor's per-URL Inspector. Open any structure gap to see
 * which page_type → target_kind pattern competitors run that we
 * don't.
 *
 * Loads on every visit (no polling) — operator-pulled.
 */
import { Link } from 'wouter';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { useOrchestrate } from '../api/hooks/useBriefings';

export default function BriefingsPage() {
  const { data, isLoading, isError, error } = useOrchestrate();

  if (isLoading) {
    return (
      <div className="bajaj-ui p-6 text-sm text-brand-text-3">
        Loading briefing… (orchestrator pulls all custodians + diff)
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="bajaj-ui p-6">
        <Card className="border-severity-error">
          <CardContent className="py-4 text-severity-error">
            {error instanceof Error ? error.message : 'Failed to load briefing'}
          </CardContent>
        </Card>
      </div>
    );
  }

  const h = data.headline;
  const cwvBad = h.cwv_worse_than_competitors || [];

  return (
    <div className="bajaj-ui p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-brand-text">
          Weekly Briefing
        </h1>
        <p className="mt-1 text-sm text-brand-text-3">
          One-shot custodian-pyramid synthesis. Refreshes when crawls land —
          02:00 IST Bajaj, 03:00 IST competitors, 02:45 IST 3D map.
          Generated {new Date(data.generated_at).toLocaleString()} ·{' '}
          {data.elapsed_ms} ms.
        </p>
      </header>

      {/* Headline KPIs */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard
          label="Competitor changes (7d)"
          value={h.total_competitor_changes_7d}
          tone={h.total_competitor_changes_7d > 20 ? 'warning' : 'neutral'}
        />
        <KpiCard
          label="Schema gaps vs theirs"
          value={h.schema_gap_count}
          tone={h.schema_gap_count > 0 ? 'warning' : 'success'}
        />
        <KpiCard
          label="Link-kind gaps"
          value={h.link_kind_gap_count}
          tone={h.link_kind_gap_count > 0 ? 'warning' : 'success'}
        />
        <KpiCard
          label="Structure gaps"
          value={h.structure_gap_count}
          tone={h.structure_gap_count > 0 ? 'warning' : 'success'}
        />
      </div>

      {/* CWV laggards */}
      {cwvBad.length > 0 && (
        <Card className="border-severity-warning">
          <CardHeader>
            <CardTitle>CWV laggard — slower than these competitors</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {cwvBad.map((d) => (
                <Badge key={d} variant="notice">
                  {d}
                </Badge>
              ))}
            </div>
            <p className="mt-2 text-xs text-brand-text-3">
              Either their median LCP is &gt; 200 ms faster than ours, or
              their PageSpeed score is &gt; 5 points higher. Open Health
              dashboard for per-URL detail.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Biggest change signals — ranked by impact */}
      <Card>
        <CardHeader>
          <div className="flex items-baseline justify-between">
            <CardTitle>Biggest competitor change signals (7d)</CardTitle>
            <Link href="/competitor-changes">
              <span className="cursor-pointer text-xs text-brand-accent hover:underline">
                See all →
              </span>
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          {h.biggest_change_signals.length === 0 ? (
            <div className="text-sm text-brand-text-3">
              No change signals yet. The 03:00 IST competitor walk + the
              ChangeWatcher will populate this once it runs.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-brand-text-3">
                <tr>
                  <th className="px-2 py-1 text-left">When</th>
                  <th className="px-2 py-1 text-left">Competitor</th>
                  <th className="px-2 py-1 text-left">Kind</th>
                  <th className="px-2 py-1 text-left">URL</th>
                </tr>
              </thead>
              <tbody>
                {h.biggest_change_signals.map((c) => (
                  <tr
                    key={`${c.competitor}-${c.url}-${c.detected_at}`}
                    className="border-t border-brand-line"
                  >
                    <td className="px-2 py-1 text-brand-text-3">
                      {c.detected_at
                        ? new Date(c.detected_at).toLocaleString()
                        : '—'}
                    </td>
                    <td className="px-2 py-1 font-medium">{c.competitor}</td>
                    <td className="px-2 py-1">
                      <Badge variant="notice">{c.kind}</Badge>
                    </td>
                    <td className="px-2 py-1 break-all">
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-accent hover:underline"
                      >
                        {c.url}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Structure-pattern gaps */}
      {data.structure_gaps && data.structure_gaps.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              Structure patterns competitors use that we don't
            </CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-xs">
              <thead className="text-brand-text-3">
                <tr>
                  <th className="px-2 py-1 text-left">On page type</th>
                  <th className="px-2 py-1 text-left">Link kind</th>
                  <th className="px-2 py-1 text-right">Our coverage</th>
                  <th className="px-2 py-1 text-right">Best competitor</th>
                  <th className="px-2 py-1 text-right">Domains with pattern</th>
                </tr>
              </thead>
              <tbody>
                {data.structure_gaps.slice(0, 20).map((g, i) => (
                  <tr
                    key={`${g.source_page_type}-${g.target_kind}-${i}`}
                    className="border-t border-brand-line"
                  >
                    <td className="px-2 py-1 font-mono">
                      {g.source_page_type}
                    </td>
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
          </CardContent>
        </Card>
      )}

      {/* Adobe top traffic */}
      {data.adobe?.available && data.adobe.top_pages && (
        <Card>
          <CardHeader>
            <CardTitle>
              Top traffic pages — last 30 days (Adobe Analytics)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-xs">
              <thead className="text-brand-text-3">
                <tr>
                  <th className="px-2 py-1 text-left">Page</th>
                  <th className="px-2 py-1 text-right">Views</th>
                </tr>
              </thead>
              <tbody>
                {data.adobe.top_pages.slice(0, 10).map((p) => (
                  <tr
                    key={p.page}
                    className="border-t border-brand-line"
                  >
                    <td className="px-2 py-1 font-mono break-all">{p.page}</td>
                    <td className="px-2 py-1 text-right">
                      {p.page_views.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.adobe.channels && (
              <div className="mt-4">
                <div className="text-xs font-semibold text-brand-text-3">
                  Channel mix:
                </div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {data.adobe.channels.slice(0, 6).map((c) => (
                    <Badge key={c.channel} variant="notice">
                      {c.channel}: {c.share_pct}%
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function KpiCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'success' | 'warning' | 'neutral';
}) {
  const colour =
    tone === 'success'
      ? 'text-severity-success'
      : tone === 'warning'
        ? 'text-severity-warning'
        : 'text-brand-text';
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-[10px] uppercase tracking-wide text-brand-text-3">
          {label}
        </div>
        <div className={`mt-1 text-3xl font-semibold ${colour}`}>{value}</div>
      </CardContent>
    </Card>
  );
}
