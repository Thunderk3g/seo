/**
 * PageDetailPage — snapshot-explicit per-URL detail.
 *
 * Mirror of CompetitorPageDetailPage's layout, but driven by an explicit
 * snapshot ID instead of (domain → latest snapshot) resolution. Used by:
 *   - Bajaj Page Explorer rows → /crawler/pages/:snapshotId/:b64
 *   - Phase 3 ad-hoc URL crawler → /adhoc/pages/:snapshotId/:b64
 *   - (Future) any caller that knows the exact snapshot.
 *
 * The render is identical to the competitor variant — operator gets the
 * same H1 tree, internal-link inventory, image audit, body, sidebar
 * CWV for Bajaj URLs as they already do for competitor URLs.
 *
 * The breadcrumb + back-link swap based on `data.snapshot_kind`, which
 * the backend returns alongside the page payload.
 */
import { Link, useParams } from 'wouter';
import { usePageDetail } from '../api/hooks/useCompetitorDetail';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';

export default function PageDetailPage() {
  const params = useParams<{ snapshotId: string; b64: string }>();
  const snapshotId = params.snapshotId || null;
  const urlB64 = params.b64 || null;
  const { data, isLoading, isError, error } = usePageDetail(snapshotId, urlB64);

  if (isLoading) {
    return (
      <div className="bajaj-ui p-6 text-sm text-brand-text-3">
        Loading page detail…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bajaj-ui p-6">
        <Card className="border-severity-error">
          <CardContent className="py-4">
            <div className="text-severity-error">
              {error instanceof Error
                ? error.message
                : 'Failed to load page detail'}
            </div>
            <Link href="/crawler">
              <Button variant="outline" size="sm" className="mt-3">
                Back to crawler
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  const kind = data.snapshot_kind || 'bajaj';
  const breadcrumb =
    kind === 'competitor' ? (
      <>
        <Link href="/competitors">
          <span className="cursor-pointer hover:underline">Competitors</span>
        </Link>
        <span className="mx-2">/</span>
        <Link
          href={`/competitors/${encodeURIComponent(data.snapshot_domain || data.domain)}`}
        >
          <span className="cursor-pointer hover:underline">
            {data.snapshot_domain || data.domain}
          </span>
        </Link>
        <span className="mx-2">/</span>
        <span>page detail</span>
      </>
    ) : kind === 'adhoc' ? (
      <>
        <Link href="/">
          <span className="cursor-pointer hover:underline">Dashboard</span>
        </Link>
        <span className="mx-2">/</span>
        <span>Ad-hoc crawl</span>
        <span className="mx-2">/</span>
        <span>page detail</span>
      </>
    ) : (
      <>
        <Link href="/crawler">
          <span className="cursor-pointer hover:underline">Bajaj crawler</span>
        </Link>
        <span className="mx-2">/</span>
        <Link href="/crawler/pages">
          <span className="cursor-pointer hover:underline">Page Explorer</span>
        </Link>
        <span className="mx-2">/</span>
        <span>page detail</span>
      </>
    );

  const sourceBadge =
    kind === 'bajaj' ? (
      <Badge variant="default">Bajaj</Badge>
    ) : kind === 'adhoc' ? (
      <Badge variant="notice">Ad-hoc</Badge>
    ) : (
      <Badge variant="outline">{data.snapshot_domain || 'Competitor'}</Badge>
    );

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6">
        <div className="text-xs text-brand-text-3">{breadcrumb}</div>
        <h1 className="mt-1 text-2xl font-semibold text-brand-text">
          {data.title || (
            <span className="italic text-brand-text-3">— no title —</span>
          )}
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
          {sourceBadge}
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

          {data.headings && data.headings.length > 0 ? (
            <Card className="mb-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Page outline
                  <span className="ml-2 text-xs font-normal text-brand-text-3">
                    {data.headings.length} heading
                    {data.headings.length === 1 ? '' : 's'}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1 text-sm">
                  {data.headings.map((h) => {
                    const indent = (h.level - 1) * 16;
                    const color =
                      h.level === 1
                        ? 'text-brand-text font-semibold'
                        : h.level === 2
                          ? 'text-brand-text font-medium'
                          : 'text-brand-text-2';
                    return (
                      <li
                        key={h.idx}
                        style={{ paddingLeft: indent }}
                        className={color}
                      >
                        <span className="mr-2 inline-block w-7 rounded bg-brand-surface-2 px-1.5 py-0.5 text-center text-[10px] font-mono uppercase text-brand-text-3">
                          h{h.level}
                        </span>
                        {h.text}
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>
          ) : (
            (data.h1_texts.length > 0 || data.h2_texts.length > 0) && (
              <Card className="mb-4">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Headings (legacy)</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  {data.h1_texts.length > 0 && (
                    <div>
                      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                        H1
                      </div>
                      <ul className="space-y-1">
                        {data.h1_texts.map((h, i) => (
                          <li
                            key={i}
                            className="font-medium text-brand-text"
                          >
                            {h}
                          </li>
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
                          <li key={i} className="text-brand-text-2">
                            {h}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          )}

          {data.internal_links && data.internal_links.length > 0 && (
            <Card className="mb-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Internal links
                  <span className="ml-2 text-xs font-normal text-brand-text-3">
                    {data.internal_links.length} ·{' '}
                    {Object.entries(
                      data.internal_links.reduce(
                        (a: Record<string, number>, l) => {
                          a[l.kind] = (a[l.kind] || 0) + 1;
                          return a;
                        },
                        {},
                      ),
                    )
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 6)
                      .map(([k, n]) => `${k}:${n}`)
                      .join(' · ')}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="max-h-96 overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-brand-surface text-left text-brand-text-3">
                      <tr>
                        <th className="px-2 py-1">Kind</th>
                        <th className="px-2 py-1">Section</th>
                        <th className="px-2 py-1">Anchor</th>
                        <th className="px-2 py-1">Href</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.internal_links.map((l, i) => (
                        <tr key={i} className="border-t border-brand-border">
                          <td className="px-2 py-1 align-top">
                            <Badge
                              variant={
                                l.kind === 'calculator'
                                  ? 'success'
                                  : 'outline'
                              }
                            >
                              {l.kind}
                            </Badge>
                          </td>
                          <td className="px-2 py-1 align-top text-brand-text-3 max-w-[12rem] truncate">
                            {l.section || '—'}
                          </td>
                          <td className="px-2 py-1 align-top text-brand-text max-w-[18rem] truncate">
                            {l.anchor || (
                              <span className="italic text-brand-text-3">
                                — no anchor —
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1 align-top font-mono">
                            <a
                              href={l.href}
                              target="_blank"
                              rel="noreferrer"
                              className="text-brand-accent hover:underline break-all"
                            >
                              {l.href}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {data.images && data.images.length > 0 && (
            <Card className="mb-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Images
                  <span className="ml-2 text-xs font-normal text-brand-text-3">
                    {data.images.length} ·{' '}
                    {data.images.filter((i) => i.alt).length} with alt
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="max-h-72 overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-brand-surface text-left text-brand-text-3">
                      <tr>
                        <th className="px-2 py-1">Alt</th>
                        <th className="px-2 py-1">Dim</th>
                        <th className="px-2 py-1">Loading</th>
                        <th className="px-2 py-1">Src</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.images.map((img, i) => (
                        <tr key={i} className="border-t border-brand-border">
                          <td className="px-2 py-1 align-top max-w-[16rem] truncate">
                            {img.alt || (
                              <span className="italic text-severity-error">
                                — missing alt —
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1 align-top font-mono text-brand-text-3">
                            {img.width && img.height
                              ? `${img.width}×${img.height}`
                              : '—'}
                          </td>
                          <td className="px-2 py-1 align-top font-mono text-brand-text-3">
                            {img.loading || '—'}
                          </td>
                          <td className="px-2 py-1 align-top font-mono">
                            <a
                              href={img.src}
                              target="_blank"
                              rel="noreferrer"
                              className="text-brand-accent hover:underline break-all"
                            >
                              {img.src}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                Body text
                <span className="ml-2 text-xs font-normal text-brand-text-3">
                  {data.body_text.length.toLocaleString()} chars ·{' '}
                  {data.word_count.toLocaleString()} words
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
                  No body text captured for this URL.
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
                  value={
                    data.lcp_ms !== null && data.lcp_ms !== undefined
                      ? `${data.lcp_ms}ms`
                      : null
                  }
                />
                <SideStat
                  label="CLS"
                  value={
                    data.cls !== null && data.cls !== undefined
                      ? data.cls.toFixed(3)
                      : null
                  }
                />
                <SideStat
                  label="INP"
                  value={
                    data.inp_ms !== null && data.inp_ms !== undefined
                      ? `${data.inp_ms}ms`
                      : null
                  }
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Structural signals</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <SideStat
                label="Response time"
                value={`${data.response_time_ms} ms`}
              />
              <SideStat
                label="Internal links"
                value={data.internal_link_count}
              />
              <SideStat
                label="External links"
                value={data.external_link_count}
              />
            </CardContent>
          </Card>

          {data.schema_types.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Schema types</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {data.schema_types.map((t) => (
                  <Badge key={t} variant="outline">
                    {t}
                  </Badge>
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
      <div className="text-xs uppercase tracking-wide text-brand-text-3">
        {label}
      </div>
      <div className="mt-0.5 text-base font-semibold text-brand-text">
        {rendered}
      </div>
    </div>
  );
}
