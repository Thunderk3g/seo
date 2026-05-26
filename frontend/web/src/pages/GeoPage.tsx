/**
 * GeoPage — `/geo-score`.
 *
 * Generative Engine Optimization rollup. Renders the unified 0-100
 * score on top + a card per factor below: page signals (citation
 * density / E-E-A-T), AI-bot hits, llms.txt presence, Reddit / Quora
 * mentions, YouTube presence, Wikidata entity, brand mentions feed.
 *
 * The "deep" toggle controls whether external SerpAPI / Wikidata
 * calls fire — operator can flip to shallow mode for a 3-second
 * page-only refresh.
 */
import { useState } from 'react';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { useGeoScore } from '../api/hooks/useBriefings';

export default function GeoPage() {
  const [deep, setDeep] = useState(true);
  const { data, isLoading, isError, error, refetch } = useGeoScore(deep);

  if (isLoading) {
    return (
      <div className="bajaj-ui p-6 text-sm text-brand-text-3">
        Computing GEO score… (deep mode hits SerpAPI + Wikidata —
        first call may take 30-60 s)
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="bajaj-ui p-6">
        <Card className="border-severity-error">
          <CardContent className="py-4 text-severity-error">
            {error instanceof Error ? error.message : 'Failed to load GEO score'}
          </CardContent>
        </Card>
      </div>
    );
  }

  const f = data.factors;
  const score = data.overall_score;
  const ring =
    score >= 70 ? 'severity-success' : score >= 40 ? 'severity-warning' : 'severity-error';

  return (
    <div className="bajaj-ui p-6 space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-brand-text">
            GEO score — {data.brand}
          </h1>
          <p className="mt-1 text-sm text-brand-text-3">
            Generative Engine Optimization. How visible is Bajaj to
            ChatGPT, Claude, Gemini, Perplexity, Bing Copilot? Each
            factor below feeds the composite score.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-brand-text-3">
            <input
              type="checkbox"
              checked={deep}
              onChange={(e) => setDeep(e.target.checked)}
            />
            Deep (external APIs)
          </label>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            Refresh
          </Button>
        </div>
      </header>

      {/* Overall score */}
      <Card>
        <CardContent className="py-6">
          <div className="flex items-center gap-6">
            <div className={`text-${ring}`}>
              <div className="text-6xl font-bold">{score}</div>
              <div className="text-xs uppercase tracking-wide text-brand-text-3">
                / 100
              </div>
            </div>
            <div className="flex-1">
              <div className="text-xs font-semibold uppercase tracking-wide text-brand-text-3 mb-2">
                Top suggestions
              </div>
              {data.suggestions.length === 0 ? (
                <div className="text-sm text-severity-success">
                  No major gaps detected.
                </div>
              ) : (
                <ul className="space-y-1 text-sm">
                  {data.suggestions.map((s, i) => (
                    <li key={i}>• {s}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Factor cards */}
      <div className="grid grid-cols-2 gap-4">
        {/* Page signals */}
        <Card>
          <CardHeader>
            <CardTitle>Page signals (citation + E-E-A-T)</CardTitle>
          </CardHeader>
          <CardContent>
            {!f.page_signals?.available ? (
              <div className="text-xs text-brand-text-3 italic">
                {f.page_signals?.reason || 'unavailable'}
              </div>
            ) : (
              <div className="space-y-1 text-xs">
                <Row k="Pages analysed" v={f.page_signals.pages_analysed} />
                <Row
                  k="Avg citation density"
                  v={`${f.page_signals.avg_citation_density}/100`}
                />
                <Row
                  k="Avg E-E-A-T score"
                  v={`${f.page_signals.avg_eeat_score}/100`}
                />
                <Row
                  k="% pages with Person schema"
                  v={`${f.page_signals.pages_with_person_schema_pct}%`}
                />
                <Row
                  k="% pages with sameAs"
                  v={`${f.page_signals.pages_with_sameas_pct}%`}
                />
              </div>
            )}
          </CardContent>
        </Card>

        {/* AI bot hits */}
        <Card>
          <CardHeader>
            <CardTitle>AI-bot hits (30 days)</CardTitle>
          </CardHeader>
          <CardContent>
            {!f.ai_bot_hits?.available ? (
              <div className="text-xs italic text-brand-text-3">
                No AIBotLog entries — ingest server logs via
                ingest_bot_logs cmd.
              </div>
            ) : (
              <div className="space-y-1 text-xs">
                <Row k="Total hits (30d)" v={f.ai_bot_hits.total_30d} />
                <Row k="Distinct bots" v={f.ai_bot_hits.distinct_bots} />
                <div className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(f.ai_bot_hits.by_bot || {}).map(
                    ([bot, n]) => (
                      <Badge key={bot} variant="notice">
                        {bot}: {n}
                      </Badge>
                    ),
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* llms.txt */}
        <Card>
          <CardHeader>
            <CardTitle>llms.txt</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 text-xs">
              <Row
                k="Present"
                v={f.llms_txt?.present ? '✓ yes' : '✗ missing'}
              />
              {f.llms_txt?.present && (
                <>
                  <Row k="Bytes" v={f.llms_txt.bytes} />
                  <Row k="URLs (approx)" v={f.llms_txt.url_count_approx} />
                </>
              )}
              {f.llms_txt?.error && (
                <div className="text-severity-warning">
                  {f.llms_txt.error}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Wikidata */}
        <Card>
          <CardHeader>
            <CardTitle>Wikidata entity</CardTitle>
          </CardHeader>
          <CardContent>
            {f.wikidata?.error && !f.wikidata.qid ? (
              <div className="text-xs italic text-severity-warning">
                {f.wikidata.error}
              </div>
            ) : (
              <div className="space-y-1 text-xs">
                <Row k="Q-id" v={f.wikidata?.qid || '—'} />
                <Row k="Label" v={f.wikidata?.label || '—'} />
                <Row
                  k="Sitelinks"
                  v={f.wikidata?.sitelinks_count ?? '—'}
                />
                <Row
                  k="Logo set"
                  v={f.wikidata?.has_logo ? '✓ yes' : '✗ no'}
                />
                {f.wikidata?.description && (
                  <div className="mt-1 text-brand-text-3 italic">
                    {f.wikidata.description}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* YouTube */}
        <Card>
          <CardHeader>
            <CardTitle>YouTube presence</CardTitle>
          </CardHeader>
          <CardContent>
            {f.youtube?.error ? (
              <div className="text-xs italic text-severity-warning">
                {f.youtube.error}
              </div>
            ) : (
              <div className="space-y-1 text-xs">
                <Row
                  k="Videos surfaced (top 10)"
                  v={f.youtube?.video_count ?? 0}
                />
                {f.youtube?.channel_url && (
                  <Row
                    k="Channel"
                    v={
                      <a
                        href={f.youtube.channel_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-accent hover:underline"
                      >
                        open
                      </a>
                    }
                  />
                )}
                {(f.youtube?.videos || []).slice(0, 3).map((v) => (
                  <div
                    key={v.link}
                    className="mt-1 break-all text-brand-text-3"
                  >
                    <a
                      href={v.link}
                      target="_blank"
                      rel="noreferrer"
                      className="text-brand-accent hover:underline"
                    >
                      {v.title}
                    </a>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Social mentions */}
        <Card>
          <CardHeader>
            <CardTitle>Reddit + Quora mentions</CardTitle>
          </CardHeader>
          <CardContent>
            {f.social_mentions?.error ? (
              <div className="text-xs italic text-severity-warning">
                {f.social_mentions.error}
              </div>
            ) : (
              <div className="space-y-1 text-xs">
                <Row
                  k="Reddit results"
                  v={f.social_mentions?.reddit_count ?? 0}
                />
                <Row
                  k="Quora results"
                  v={f.social_mentions?.quora_count ?? 0}
                />
                <p className="mt-1 text-brand-text-3">
                  ChatGPT and Perplexity weight these surfaces heavily.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Brand mentions feed */}
        <Card>
          <CardHeader>
            <CardTitle>Brand mentions feed (30 days)</CardTitle>
          </CardHeader>
          <CardContent>
            {!f.brand_mentions?.available ? (
              <div className="text-xs italic text-brand-text-3">
                {f.brand_mentions?.error || 'unavailable'}
              </div>
            ) : (
              <div className="space-y-1 text-xs">
                <Row
                  k="Total mentions (30d)"
                  v={f.brand_mentions.count_30d}
                />
                <div className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(f.brand_mentions.tier_breakdown || {}).map(
                    ([tier, n]) => (
                      <Badge key={tier} variant="notice">
                        {tier}: {n}
                      </Badge>
                    ),
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Row({
  k,
  v,
}: {
  k: string;
  v: number | string | null | undefined | React.ReactNode;
}) {
  return (
    <div className="flex justify-between">
      <span className="text-brand-text-3">{k}</span>
      <span className="font-medium">{v ?? '—'}</span>
    </div>
  );
}
