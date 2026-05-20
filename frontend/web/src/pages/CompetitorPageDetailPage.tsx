/**
 * CompetitorPageDetailPage — `/competitors/<domain>/pages/<b64url>`.
 *
 * Full per-URL detail. Replaces the raw-text body dump that lived
 * inside the DeepCrawlPanel expandable rows. Renders:
 *
 *   * Page header with domain breadcrumb + external link + KPIs
 *   * Schema-type chips, meta description, H1/H2 lists
 *   * Body text in a readable typographic block (whitespace preserved)
 *   * Sidebar with CWV grid + link counts
 *
 * Body text comes from the competitor crawler's full-body capture
 * (commit 1f78935 onwards). No emojis. Bajaj brand throughout.
 */
import { Link, useParams } from 'wouter';
import { useCompetitorPageDetail } from '../api/hooks/useCompetitorDetail';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';

export default function CompetitorPageDetailPage() {
  const params = useParams<{ domain: string; b64: string }>();
  const domain = params.domain ? decodeURIComponent(params.domain) : null;
  const urlB64 = params.b64 || null;
  const { data, isLoading, isError, error } = useCompetitorPageDetail(domain, urlB64);

  if (isLoading) {
    return (
      <div className="bajaj-ui p-6 text-sm text-brand-text-3">Loading page detail…</div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bajaj-ui p-6">
        <Card className="border-severity-error">
          <CardContent className="py-4">
            <div className="text-severity-error">
              {error instanceof Error ? error.message : 'Failed to load page detail'}
            </div>
            {domain && (
              <Link href={`/competitors/${encodeURIComponent(domain)}`}>
                <Button variant="outline" size="sm" className="mt-3">
                  Back to {domain}
                </Button>
              </Link>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6">
        <div className="text-xs text-brand-text-3">
          <Link href="/competitors">
            <span className="cursor-pointer hover:underline">Competitors</span>
          </Link>
          <span className="mx-2">/</span>
          <Link href={`/competitors/${encodeURIComponent(data.domain)}`}>
            <span className="cursor-pointer hover:underline">{data.domain}</span>
          </Link>
          <span className="mx-2">/</span>
          <span>page detail</span>
        </div>
        <h1 className="mt-1 text-2xl font-semibold text-brand-text">
          {data.title || <span className="italic text-brand-text-3">— no title —</span>}
        </h1>
        <a
          href={data.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block break-all font-mono text-xs text-brand-accent hover:underline"
        >
          {data.url}
        </a>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {data.page_type && <Badge variant="notice">{data.page_type}</Badge>}
          {data.has_schema && <Badge variant="success">schema</Badge>}
          {data.last_modified && (
            <Badge variant="outline">
              modified {new Date(data.last_modified).toLocaleDateString()}
            </Badge>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {data.meta_description && (
            <Card className="mb-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Meta description</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-brand-text-2">
                {data.meta_description}
              </CardContent>
            </Card>
          )}

          {(data.h1_texts.length > 0 || data.h2_texts.length > 0) && (
            <Card className="mb-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Headings</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {data.h1_texts.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                      H1
                    </div>
                    <ul className="space-y-1">
                      {data.h1_texts.map((h, i) => (
                        <li key={i} className="font-medium text-brand-text">{h}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {data.h2_texts.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                      H2 ({data.h2_texts.length})
                    </div>
                    <ul className="space-y-1">
                      {data.h2_texts.slice(0, 12).map((h, i) => (
                        <li key={i} className="text-brand-text-2">{h}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                Body text
                <span className="ml-2 text-xs font-normal text-brand-text-3">
                  {data.body_text.length.toLocaleString()} chars · {data.word_count.toLocaleString()} words
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.body_text ? (
                <div className="rounded-md bg-brand-surface-2 p-4 text-sm leading-relaxed text-brand-text whitespace-pre-wrap break-words">
                  {data.body_text}
                </div>
              ) : (
                <div className="italic text-brand-text-3">
                  No body text captured. Re-run the gap pipeline to populate.
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Core Web Vitals</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <SideStat label="PageSpeed" value={data.pagespeed_score} />
                <SideStat
                  label="LCP"
                  value={data.lcp_ms !== null && data.lcp_ms !== undefined ? `${data.lcp_ms}ms` : null}
                />
                <SideStat
                  label="CLS"
                  value={data.cls !== null && data.cls !== undefined ? data.cls.toFixed(3) : null}
                />
                <SideStat
                  label="INP"
                  value={data.inp_ms !== null && data.inp_ms !== undefined ? `${data.inp_ms}ms` : null}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Structural signals</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <SideStat label="Response time" value={`${data.response_time_ms} ms`} />
              <SideStat label="Internal links" value={data.internal_link_count} />
              <SideStat label="External links" value={data.external_link_count} />
            </CardContent>
          </Card>

          {data.schema_types.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Schema types</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {data.schema_types.map((t) => (
                  <Badge key={t} variant="outline">{t}</Badge>
                ))}
              </CardContent>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

function SideStat({
  label,
  value,
}: {
  label: string;
  value: number | string | null | undefined;
}) {
  const rendered =
    value === null || value === undefined || value === ''
      ? '—'
      : typeof value === 'number'
        ? value.toLocaleString()
        : value;
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-brand-text-3">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-brand-text">{rendered}</div>
    </div>
  );
}
