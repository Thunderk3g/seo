// CompetitorsPage — surfaces the four-dimension competitor gap report
// computed by `apps.seo_ai.scoring_competitor`, backed by
// `/api/v1/seo/competitor/`. Sections, top to bottom:
//
//   1. KPI strip               — competitors / pages crawled / gaps found
//   2. Competitor roster table — each rival with overlap + crawl stats
//   3. Topic gaps              — clusters they cover that we don't
//   4. Keyword gaps            — top SERP-1 queries we miss entirely
//   5. Hygiene deltas          — per-cluster title/meta/H1/schema gap
//   6. Content volume deltas   — per-cluster page count + word count gap
//
// The page is informational. The Grade page Findings tab is where the
// LLM narrates *what to do*; this page shows the *raw evidence*.

import { useCompetitorDashboard } from '../api/hooks/useCompetitorDashboard';
import type {
  CompetitorDashboard,
  CompetitorHygieneDelta,
  CompetitorKeywordGap,
  CompetitorSummary,
  CompetitorTopicGap,
  CompetitorVolumeDelta,
} from '../api/seoTypes';
import GapDetectionSection from '../components/competitors/GapDetectionSection';

export default function CompetitorsPage() {
  const { data, isLoading, isError, error } = useCompetitorDashboard();

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Competitor Gap</h1>
          <div className="seo-page-sub">
            Top organic rivals discovered via SEMrush, with the topic /
            keyword / hygiene / content-depth gaps that explain where{' '}
            <b>bajajlifeinsurance.com</b> trails. Source data feeds the
            CompetitorAgent in the SEO Grade run.
          </div>
        </div>
      </header>

      {isLoading && (
        <div className="seo-empty">
          Building the competitor gap report. First-run can take 3–7
          minutes (SEMrush pulls + polite crawl of ~500 rival pages at
          1 req/sec). Cached for 7 days after that.
        </div>
      )}
      {isError && (
        <div className="seo-error">
          Failed to fetch competitor data:{' '}
          {error instanceof Error ? error.message : 'unknown error'}
        </div>
      )}
      {data && !data.available && (
        <div className="seo-empty">
          Competitor analysis is unavailable.{' '}
          {data.error ? <span>({data.error})</span> : null}
          {' '}Set <b>SEMRUSH_API_KEY</b> and{' '}
          <b>COMPETITOR_ENABLED=true</b> to enable.
        </div>
      )}

      {data && data.available && <CompetitorBody data={data} />}

      {/* Phase-2 detection layer — 7 agent cards. Renders even when
          the legacy competitor dashboard above is unavailable. */}
      <GapDetectionSection domain={data?.domain} />
    </div>
  );
}

function CompetitorBody({ data }: { data: CompetitorDashboard }) {
  const s = data.summary!;
  return (
    <>
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Competitor overview</h2>
          <span className="seo-card-sub">
            Source: SEMrush + polite HTML crawl
          </span>
        </div>
        <div className="seo-perf-totals">
          <Kpi
            label="Competitors analysed"
            value={s.competitors_analysed.toLocaleString()}
          />
          <Kpi
            label="Pages crawled"
            value={`${s.competitor_pages_crawled_ok} / ${s.competitor_pages_crawl_attempted}`}
          />
          <Kpi
            label="Topic gaps"
            value={s.topic_gaps_found.toLocaleString()}
          />
          <Kpi
            label="Keyword gaps"
            value={s.keyword_gaps_found.toLocaleString()}
          />
          <Kpi
            label="Hygiene deltas"
            value={s.hygiene_deltas_found.toLocaleString()}
          />
          <Kpi
            label="Content volume deltas"
            value={s.content_volume_deltas_found.toLocaleString()}
          />
        </div>
      </div>

      <CompetitorRoster rows={data.competitors ?? []} />

      <div className="seo-row-2-balanced">
        <TopicGapsCard rows={data.topic_gaps ?? []} />
        <KeywordGapsCard rows={data.keyword_gaps ?? []} />
      </div>

      <div className="seo-row-2-balanced">
        <HygieneDeltasCard rows={data.hygiene_deltas ?? []} />
        <VolumeDeltasCard rows={data.content_volume_deltas ?? []} />
      </div>
    </>
  );
}

function CompetitorRoster({ rows }: { rows: CompetitorSummary[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Competitors</h2>
        <span className="seo-card-sub">
          ranked by SEMrush competition level
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No competitors discovered.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Domain</th>
              <th className="num">Competition</th>
              <th className="num">Common kw</th>
              <th className="num">Top pages pulled</th>
              <th className="num">Keywords pulled</th>
              <th className="num">Crawled OK</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.domain}>
                <td className="seo-cell-query" title={r.domain}>
                  <a
                    href={`https://${r.domain}/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {r.domain}
                  </a>
                </td>
                <td className="num">{r.competition_level.toFixed(2)}</td>
                <td className="num">{r.common_keywords.toLocaleString()}</td>
                <td className="num">{r.top_pages_pulled}</td>
                <td className="num">{r.keywords_pulled}</td>
                <td
                  className={`num ${
                    r.pages_crawled_ok === 0 ? 'seo-mover-down' : ''
                  }`}
                >
                  {r.pages_crawled_ok} / {r.pages_crawl_attempted}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TopicGapsCard({ rows }: { rows: CompetitorTopicGap[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Topic gaps</h2>
        <span className="seo-card-sub">
          topics rivals cover that we don't
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No topic gaps found in this sample.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Topic</th>
              <th className="num">Their pages</th>
              <th className="num">Our pages</th>
              <th>Covering rivals</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.cluster_slug}>
                <td>{r.cluster_slug}</td>
                <td className="num">{r.competitor_page_count}</td>
                <td
                  className={`num ${
                    r.our_page_count === 0 ? 'seo-mover-down' : ''
                  }`}
                >
                  {r.our_page_count}
                </td>
                <td className="seo-cell-query">
                  {r.competitors_covering.join(', ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function KeywordGapsCard({ rows }: { rows: CompetitorKeywordGap[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Keyword gaps</h2>
        <span className="seo-card-sub">
          rivals rank top-10 · we don't rank at all
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No keyword gaps found.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Keyword</th>
              <th>Rival</th>
              <th className="num">Pos</th>
              <th className="num">Volume</th>
              <th className="num">Traffic %</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 25).map((r) => (
              <tr key={`${r.keyword}-${r.competitor_domain}`}>
                <td className="seo-cell-query" title={r.keyword}>
                  {r.keyword}
                </td>
                <td className="seo-cell-query" title={r.competitor_domain}>
                  {r.competitor_domain}
                </td>
                <td className="num">{r.competitor_position}</td>
                <td className="num">{compact(r.search_volume)}</td>
                <td className="num">
                  {r.competitor_traffic_pct.toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function HygieneDeltasCard({ rows }: { rows: CompetitorHygieneDelta[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>On-page hygiene gaps</h2>
        <span className="seo-card-sub">
          title / meta / H1 / schema vs rivals, per topic
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No hygiene deltas found.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Topic</th>
              <th className="num">Title (us / them)</th>
              <th className="num">Desc (us / them)</th>
              <th className="num">H1 % (us / them)</th>
              <th className="num">Schema % (us / them)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.cluster_slug}>
                <td>{r.cluster_slug}</td>
                <td className="num">
                  {r.our_avg_title_length.toFixed(0)} /{' '}
                  <b>{r.competitor_avg_title_length.toFixed(0)}</b>
                </td>
                <td className="num">
                  {r.our_avg_description_length.toFixed(0)} /{' '}
                  <b>{r.competitor_avg_description_length.toFixed(0)}</b>
                </td>
                <td
                  className={`num ${
                    r.competitor_h1_pct - r.our_h1_pct >= 20
                      ? 'seo-mover-down'
                      : ''
                  }`}
                >
                  {r.our_h1_pct.toFixed(0)} /{' '}
                  <b>{r.competitor_h1_pct.toFixed(0)}</b>
                </td>
                <td
                  className={`num ${
                    r.competitor_schema_pct - r.our_schema_pct >= 20
                      ? 'seo-mover-down'
                      : ''
                  }`}
                >
                  {r.our_schema_pct.toFixed(0)} /{' '}
                  <b>{r.competitor_schema_pct.toFixed(0)}</b>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function VolumeDeltasCard({ rows }: { rows: CompetitorVolumeDelta[] }) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Content depth gaps</h2>
        <span className="seo-card-sub">
          page count + word count per topic
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No content volume deltas found.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Topic</th>
              <th className="num">Pages (us / them)</th>
              <th className="num">Avg words (us / them)</th>
              <th className="num">Total words gap</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.cluster_slug}>
                <td>{r.cluster_slug}</td>
                <td className="num">
                  {r.our_page_count} / <b>{r.competitor_page_count}</b>
                </td>
                <td className="num">
                  {compact(Math.round(r.our_avg_word_count))} /{' '}
                  <b>{compact(Math.round(r.competitor_avg_word_count))}</b>
                </td>
                <td className="num seo-mover-down">
                  -{compact(r.competitor_total_words - r.our_total_words)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="seo-perf-total">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}
