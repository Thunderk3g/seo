// AdobePage — Adobe Analytics 2.0 dashboard, full Tier 1-3 surface.
//
// Eight tabs, each pulling from /api/v1/seo/adobe/?lookback=N&limit=M.
// Every section is independently cached on disk by the backend; if a
// live Adobe call fails, the dashboard falls back to the most recent
// successful pull and tags the section "cached <N>h ago" so the
// operator can see what's stale at a glance.
//
//   1. Overview      — KPIs, daily trend (+YoY overlay if available),
//                      marketing channels, freshness banner
//   2. Content       — top pages, entry pages, exit pages, site sections,
//                      page-not-found
//   3. Behaviour     — visitors / unique / engagement summary,
//                      internal search terms
//   4. Acquisition   — channels + sub-channel detail, referrer domains,
//                      search engines
//   5. Geo           — countries, regions, cities, languages
//   6. Tech          — devices, browsers, OS, resolutions
//   7. Time          — hour-of-day, day-of-week
//   8. Workspace     — segments + calculated metrics catalogue + lead
//                      events + per-section freshness audit
//
// Bajaj brand non-negotiable — same `seo-card` styling, same Bajaj
// blue palette anchor.

import { useMemo, useState } from 'react';
import {
  useAdobeDashboard,
  type AdobeBrowserRow,
  type AdobeCachedSection,
  type AdobeCatalogueItem,
  type AdobeChannelRow,
  type AdobeDailyPoint,
  type AdobeDashboardResponse,
  type AdobeDeviceRow,
  type AdobeEntryPageRow,
  type AdobeExitPageRow,
  type AdobeFreshness,
  type AdobeGeoRow,
  type AdobeHourRow,
  type AdobeInternalSearchRow,
  type AdobeLangRow,
  type AdobeLeadEventRow,
  type AdobeNotFoundRow,
  type AdobeOSRow,
  type AdobeReferrerDomainRow,
  type AdobeResolutionRow,
  type AdobeSearchEngineRow,
  type AdobeSiteSectionRow,
  type AdobeTopPageRow,
  type AdobeVisitorsSummary,
  type AdobeWeekdayRow,
} from '../api/hooks/useAdobeDashboard';
import TimeSeriesChart from '../components/charts/TimeSeriesChart';
import MiniDonut from '../components/charts/MiniDonut';

const LOOKBACK_OPTIONS = [7, 14, 30];
const LIMIT_OPTIONS = [25, 50, 100];

const PALETTE = [
  '#0072ce', // Bajaj blue
  '#21a884',
  '#f4a300',
  '#d24a3e',
  '#7b6cc4',
  '#15788c',
  '#c46b14',
  '#3c6d28',
  '#888aa0',
  '#9f4d99',
];

type TabId =
  | 'overview'
  | 'content'
  | 'behaviour'
  | 'acquisition'
  | 'geo'
  | 'tech'
  | 'time'
  | 'workspace';

const TABS: Array<{ id: TabId; label: string; hint: string }> = [
  { id: 'overview',    label: 'Overview',    hint: 'KPIs, trend, channels, freshness' },
  { id: 'content',     label: 'Content',     hint: 'Top, entry, exit, sections, 404s' },
  { id: 'behaviour',   label: 'Behaviour',   hint: 'Visitors, engagement, internal search' },
  { id: 'acquisition', label: 'Acquisition', hint: 'Channel detail, referrers, engines' },
  { id: 'geo',         label: 'Geo',         hint: 'Country, region, city, language' },
  { id: 'tech',        label: 'Tech',        hint: 'Device, browser, OS, resolution' },
  { id: 'time',        label: 'Time',        hint: 'Hour-of-day, day-of-week' },
  { id: 'workspace',   label: 'Workspace',   hint: 'Segments, calc metrics, lead events, cache audit' },
];

export default function AdobePage() {
  const [lookback, setLookback] = useState<number>(7);
  const [limit, setLimit] = useState<number>(25);
  const [tab, setTab] = useState<TabId>('overview');
  const { data, isLoading, isError } = useAdobeDashboard(lookback, limit);

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Adobe Analytics</h1>
          <div className="seo-page-sub">
            Behaviour and page performance for{' '}
            <b>
              {data?.report_suite?.name ||
                data?.rsid ||
                'bajajallianzbalicprod'}
            </b>
            {data?.global_company_id ? (
              <>
                {' '}· Company <code>{data.global_company_id}</code>
              </>
            ) : null}
            {data?.lookback_days
              ? ` · Last ${data.lookback_days} days`
              : null}
          </div>
        </div>
        <div className="seo-page-controls">
          <label className="seo-control">
            <span>Lookback</span>
            <select
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value))}
            >
              {LOOKBACK_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </select>
          </label>
          <label className="seo-control">
            <span>Top pages</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  Top {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {isLoading && (
        <div className="seo-empty">
          Loading Adobe Analytics data… first call can take 30-60 s while
          we pull ~25 reports.
        </div>
      )}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server is
          running on /api/v1/seo/.
        </div>
      )}

      {data && !data.available && (
        <div className="seo-empty">
          Adobe Analytics is not configured.{' '}
          {data.reason === 'not_configured' ? (
            <>
              Set <b>ADOBE_CLIENT_ID</b>, <b>ADOBE_CLIENT_SECRET</b>,{' '}
              <b>ADOBE_GLOBAL_COMPANY_ID</b>, and <b>ADOBE_RSID</b> in the
              backend <code>.env</code> and reload.
            </>
          ) : (
            <span>{data.error}</span>
          )}
        </div>
      )}

      {data && data.available && (
        <>
          <FreshnessBanner data={data} />
          <div className="competitor-tab-strip">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={'tab ' + (tab === t.id ? 'active' : '')}
                onClick={() => setTab(t.id)}
                title={t.hint}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="competitor-tab-body">
            {tab === 'overview' && <OverviewTab data={data} />}
            {tab === 'content' && <ContentTab data={data} />}
            {tab === 'behaviour' && <BehaviourTab data={data} />}
            {tab === 'acquisition' && <AcquisitionTab data={data} />}
            {tab === 'geo' && <GeoTab data={data} />}
            {tab === 'tech' && <TechTab data={data} />}
            {tab === 'time' && <TimeTab data={data} />}
            {tab === 'workspace' && <WorkspaceTab data={data} />}
          </div>
        </>
      )}
    </div>
  );
}

// ── Freshness banner — global heads-up if anything is stale ──────────

function FreshnessBanner({ data }: { data: AdobeDashboardResponse }) {
  const fr = data.data_freshness ?? {};
  const total = Object.keys(fr).length;
  if (total === 0) return null;
  const counts: Record<AdobeFreshness, number> = {
    live: 0,
    cached: 0,
    missing: 0,
  };
  Object.values(fr).forEach((s) => {
    counts[s] = (counts[s] ?? 0) + 1;
  });
  if (counts.cached === 0 && counts.missing === 0) {
    return (
      <div
        className="seo-card-foot"
        style={{ color: 'var(--text-2)', marginBottom: 8 }}
      >
        ✓ All {total} sections pulled live this request.
      </div>
    );
  }
  return (
    <div className="seo-card" style={{ marginBottom: 8, borderColor: '#f4a300' }}>
      <div className="seo-card-head">
        <h2 style={{ color: '#c46b14' }}>Partial freshness</h2>
        <span className="seo-card-sub">
          {counts.live} live · {counts.cached} cached · {counts.missing} missing
          {' '}— cached sections render the most recent successful pull.
        </span>
      </div>
    </div>
  );
}

function FreshnessTag({
  status,
  ageSec,
}: {
  status?: AdobeFreshness;
  ageSec?: number;
}) {
  if (!status || status === 'live') {
    return (
      <span
        style={{
          fontSize: 11,
          color: '#21a884',
          marginLeft: 6,
        }}
      >
        ● live
      </span>
    );
  }
  if (status === 'missing') {
    return (
      <span
        style={{
          fontSize: 11,
          color: 'var(--text-3)',
          marginLeft: 6,
        }}
      >
        ○ no data
      </span>
    );
  }
  const ageLabel =
    ageSec === undefined
      ? 'cached'
      : ageSec < 60
        ? `${ageSec}s ago`
        : ageSec < 3600
          ? `${Math.round(ageSec / 60)}m ago`
          : ageSec < 86400
            ? `${Math.round(ageSec / 3600)}h ago`
            : `${Math.round(ageSec / 86400)}d ago`;
  return (
    <span
      style={{
        fontSize: 11,
        color: '#c46b14',
        marginLeft: 6,
      }}
    >
      ◐ cached · {ageLabel}
    </span>
  );
}

// ── 1. Overview tab ──────────────────────────────────────────────────

function OverviewTab({ data }: { data: AdobeDashboardResponse }) {
  const totals = data.totals ?? {};
  const trend = data.daily_trend ?? [];
  const yoy = data.yoy_daily_trend ?? [];
  const channels = data.channels ?? [];

  // Compose YoY chart: same date keys, but the YoY series shifts a year
  // ahead so they overlay visually.
  const trendData = useMemo(() => {
    const yoyByDate = new Map<string, number>();
    yoy.forEach((p) => {
      // Add a year to align YoY date with current series.
      try {
        const d = new Date(p.date);
        d.setFullYear(d.getFullYear() + 1);
        yoyByDate.set(d.toISOString().slice(0, 10), p.page_views);
      } catch {
        // ignore
      }
    });
    return trend.map((p) => ({
      date: p.date,
      'Page views': p.page_views,
      Visits: p.visits,
      'Page views (1 yr ago)': yoyByDate.get(p.date) ?? null,
    }));
  }, [trend, yoy]);

  return (
    <>
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Window summary</h2>
          <span className="seo-card-sub">
            {data.report_suite?.rsid ?? data.rsid} · Last{' '}
            {data.lookback_days ?? '?'} days
          </span>
        </div>
        <div className="seo-perf-totals">
          <Kpi label="Total page-views" value={compact(totals.total_views)} />
          <Kpi label="Pages with traffic" value={compact(totals.total_pages)} />
          <Kpi label="Top-page views" value={compact(totals.col_max)} />
          <Kpi label="Dimensions" value={compact(data.dimension_count)} />
          <Kpi label="Metrics" value={compact(data.metric_count)} />
        </div>
      </div>

      <div className="seo-card">
        <div className="seo-card-head">
          <h2>
            Daily trend
            <FreshnessTag
              status={data.data_freshness?.daily_trend}
              ageSec={data.data_age_sec?.daily_trend}
            />
          </h2>
          <span className="seo-card-sub">
            Last {trend.length || 30} days · page-views, visits
            {yoy.length > 0
              ? ` · with YoY overlay (${yoy.length} prior-year days)`
              : ''}
          </span>
        </div>
        <TimeSeriesChart
          data={trendData}
          series={[
            {
              key: 'Page views',
              label: 'Page views',
              color: 'var(--accent)',
              fill: true,
            },
            { key: 'Visits', label: 'Visits', color: '#21a884' },
            ...(yoy.length > 0
              ? [
                  {
                    key: 'Page views (1 yr ago)',
                    label: 'Page views (1 yr ago)',
                    color: '#888aa0',
                  },
                ]
              : []),
          ]}
          height={260}
        />
      </div>

      <div className="seo-card">
        <div className="seo-card-head">
          <h2>
            Marketing channels
            <FreshnessTag
              status={data.data_freshness?.channels}
              ageSec={data.data_age_sec?.channels}
            />
          </h2>
          <span className="seo-card-sub">
            Visits by channel · last {data.lookback_days ?? '?'} days
          </span>
        </div>
        <ChannelsSection rows={channels} />
      </div>
    </>
  );
}

// ── 2. Content tab ───────────────────────────────────────────────────

function ContentTab({ data }: { data: AdobeDashboardResponse }) {
  return (
    <>
      <Section
        title="Top pages by page-views"
        subtitle={`${data.top_pages?.length ?? 0} rows · current window`}
        status={data.data_freshness?.top_pages}
        ageSec={data.data_age_sec?.top_pages}
      >
        {(data.top_pages?.length ?? 0) === 0 ? (
          <div className="seo-empty">No data for this window.</div>
        ) : (
          <TopPagesTable rows={data.top_pages ?? []} />
        )}
      </Section>

      <Section
        title="Entry pages"
        subtitle="With bounce-rate + avg time on page"
        status={data.data_freshness?.entry_pages}
        ageSec={data.data_age_sec?.entry_pages}
      >
        {(data.entry_pages?.length ?? 0) === 0 ? (
          <div className="seo-empty">
            No entry-page data — dimension may not be enabled on this report
            suite, or the lookback window has no entry events.
          </div>
        ) : (
          <EntryPagesTable rows={data.entry_pages ?? []} />
        )}
      </Section>

      <Section
        title="Exit pages"
        subtitle="Where visits end — funnel-leak diagnostic"
        status={data.data_freshness?.exit_pages}
        ageSec={data.data_age_sec?.exit_pages}
      >
        <ExitPagesTable rows={data.exit_pages ?? []} />
      </Section>

      <Section
        title="Site sections"
        subtitle="Pages rolled up by their Launch-tagged section variable"
        status={data.data_freshness?.site_sections}
        ageSec={data.data_age_sec?.site_sections}
      >
        <SiteSectionsTable rows={data.site_sections ?? []} />
      </Section>

      <Section
        title="Page-not-found errors"
        subtitle="Adobe-tracked 404 URLs (depends on Launch instrumentation)"
        status={data.data_freshness?.page_not_found}
        ageSec={data.data_age_sec?.page_not_found}
      >
        <NotFoundTable rows={data.page_not_found ?? []} />
      </Section>
    </>
  );
}

// ── 3. Behaviour tab ─────────────────────────────────────────────────

function BehaviourTab({ data }: { data: AdobeDashboardResponse }) {
  const vs = data.visitors_summary ?? {};
  return (
    <>
      <Section
        title="Audience + engagement"
        subtitle="Visitors, unique visitors, time on site, page depth, bounce, exits"
        status={data.data_freshness?.visitors_summary}
        ageSec={data.data_age_sec?.visitors_summary}
      >
        <VisitorsSummaryStrip vs={vs} />
      </Section>

      <Section
        title="Internal site search"
        subtitle="What users typed into our on-site search — content-gap discovery"
        status={data.data_freshness?.internal_searches}
        ageSec={data.data_age_sec?.internal_searches}
      >
        <InternalSearchTable rows={data.internal_searches ?? []} />
      </Section>
    </>
  );
}

// ── 4. Acquisition tab ───────────────────────────────────────────────

function AcquisitionTab({ data }: { data: AdobeDashboardResponse }) {
  return (
    <>
      <Section
        title="Channel sub-detail"
        subtitle="Same channel split as Overview but broken out further (Organic → Google vs Bing, Paid → Search vs Display)"
        status={data.data_freshness?.channel_detail}
        ageSec={data.data_age_sec?.channel_detail}
      >
        {(data.channel_detail?.length ?? 0) === 0 ? (
          <div className="seo-empty">
            No channel-detail data — dimension may not be enabled.
          </div>
        ) : (
          <ShareTable
            rows={(data.channel_detail ?? []).map((r) => ({
              label: r.channel,
              count: r.visits,
              share: r.share_pct,
            }))}
            unit="Visits"
            emptyMsg=""
          />
        )}
      </Section>

      <Section
        title="Referring domains"
        subtitle="Third-party sites driving traffic (partial substitute for GSC Links)"
        status={data.data_freshness?.referrer_domains}
        ageSec={data.data_age_sec?.referrer_domains}
      >
        <ShareTable
          rows={(data.referrer_domains ?? []).map((r) => ({
            label: r.domain,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No referring-domain data."
        />
      </Section>

      <Section
        title="Search engines"
        subtitle="Organic traffic split by engine"
        status={data.data_freshness?.search_engines}
        ageSec={data.data_age_sec?.search_engines}
      >
        <ShareTable
          rows={(data.search_engines ?? []).map((r) => ({
            label: r.engine,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No engine-level data."
        />
      </Section>
    </>
  );
}

// ── 5. Geo tab ───────────────────────────────────────────────────────

function GeoTab({ data }: { data: AdobeDashboardResponse }) {
  return (
    <>
      <Section
        title="Countries"
        subtitle="Top countries by visits"
        status={data.data_freshness?.countries}
        ageSec={data.data_age_sec?.countries}
      >
        <ShareTable
          rows={(data.countries ?? []).map((r) => ({
            label: r.label,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No country data."
        />
      </Section>

      <Section
        title="Regions / states"
        subtitle="India-focused — Maharashtra / Karnataka / Delhi, etc."
        status={data.data_freshness?.regions}
        ageSec={data.data_age_sec?.regions}
      >
        <ShareTable
          rows={(data.regions ?? []).map((r) => ({
            label: r.label,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No region data."
        />
      </Section>

      <Section
        title="Cities"
        subtitle="Top cities by visits"
        status={data.data_freshness?.cities}
        ageSec={data.data_age_sec?.cities}
      >
        <ShareTable
          rows={(data.cities ?? []).map((r) => ({
            label: r.label,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No city data."
        />
      </Section>

      <Section
        title="Languages"
        subtitle="Browser-detected language preference"
        status={data.data_freshness?.languages}
        ageSec={data.data_age_sec?.languages}
      >
        <ShareTable
          rows={(data.languages ?? []).map((r) => ({
            label: r.language,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No language data."
        />
      </Section>
    </>
  );
}

// ── 6. Tech tab ──────────────────────────────────────────────────────

function TechTab({ data }: { data: AdobeDashboardResponse }) {
  return (
    <>
      <Section
        title="Devices"
        subtitle="Mobile / Tablet / Desktop / Other"
        status={data.data_freshness?.devices}
        ageSec={data.data_age_sec?.devices}
      >
        <ShareTable
          rows={(data.devices ?? []).map((r) => ({
            label: r.device_type,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No device data."
        />
      </Section>

      <Section
        title="Browsers"
        subtitle="Per-browser visit count"
        status={data.data_freshness?.browsers}
        ageSec={data.data_age_sec?.browsers}
      >
        <ShareTable
          rows={(data.browsers ?? []).map((r) => ({
            label: r.browser,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No browser data."
        />
      </Section>

      <Section
        title="Operating systems"
        subtitle="iOS vs Android vs Windows vs macOS"
        status={data.data_freshness?.operating_systems}
        ageSec={data.data_age_sec?.operating_systems}
      >
        <ShareTable
          rows={(data.operating_systems ?? []).map((r) => ({
            label: r.os_name,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No OS data."
        />
      </Section>

      <Section
        title="Screen resolutions"
        subtitle="Most common viewport sizes — UX / CLS audit targets"
        status={data.data_freshness?.resolutions}
        ageSec={data.data_age_sec?.resolutions}
      >
        <ShareTable
          rows={(data.resolutions ?? []).map((r) => ({
            label: r.resolution,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No resolution data."
        />
      </Section>
    </>
  );
}

// ── 7. Time tab ──────────────────────────────────────────────────────

function TimeTab({ data }: { data: AdobeDashboardResponse }) {
  return (
    <>
      <Section
        title="Hour of day"
        subtitle="When users hit the site — crawl off-peak, ad-spend pacing"
        status={data.data_freshness?.hours}
        ageSec={data.data_age_sec?.hours}
      >
        <HourTable rows={data.hours ?? []} />
      </Section>

      <Section
        title="Day of week"
        subtitle="Mon-Sun pattern (30-day window)"
        status={data.data_freshness?.weekdays}
        ageSec={data.data_age_sec?.weekdays}
      >
        <ShareTable
          rows={(data.weekdays ?? []).map((r) => ({
            label: r.weekday,
            count: r.visits,
            share: r.share_pct,
          }))}
          unit="Visits"
          emptyMsg="No weekday data."
        />
      </Section>
    </>
  );
}

// ── 8. Workspace tab — catalogues + cache audit + lead events ────────

function WorkspaceTab({ data }: { data: AdobeDashboardResponse }) {
  return (
    <>
      <Section
        title="Lead events"
        subtitle="Distinct values of the ADOBE_LEAD_HASH_EVAR dimension"
        status={data.data_freshness?.lead_events}
        ageSec={data.data_age_sec?.lead_events}
      >
        <LeadEventsTable rows={data.lead_events ?? []} />
      </Section>

      <Section
        title="Segments catalogue"
        subtitle="Read-only list of Workspace segments your analytics team maintains"
        status={data.data_freshness?.segments}
        ageSec={data.data_age_sec?.segments}
      >
        <CatalogueTable rows={data.segments ?? []} kind="segment" />
      </Section>

      <Section
        title="Calculated metrics catalogue"
        subtitle="Workspace calculated metrics — apply via the metric picker (future)"
        status={data.data_freshness?.calculated_metrics}
        ageSec={data.data_age_sec?.calculated_metrics}
      >
        <CatalogueTable
          rows={data.calculated_metrics ?? []}
          kind="calculated metric"
        />
      </Section>

      <CacheAuditCard cached={data.cached_sections_on_disk ?? {}} />
    </>
  );
}

// ── shared sub-components ────────────────────────────────────────────

function Section({
  title,
  subtitle,
  status,
  ageSec,
  children,
}: {
  title: string;
  subtitle?: string;
  status?: AdobeFreshness;
  ageSec?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>
          {title}
          <FreshnessTag status={status} ageSec={ageSec} />
        </h2>
        {subtitle && <span className="seo-card-sub">{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function VisitorsSummaryStrip({ vs }: { vs: AdobeVisitorsSummary }) {
  if (!vs || Object.keys(vs).length === 0) {
    return (
      <div className="seo-empty">
        Audience-summary metrics aren't returning data for this suite.
        Often this means <code>metrics/pagesperVisit</code> or{' '}
        <code>metrics/uniquevisitors</code> aren't exposed under your
        Workspace permissions. Try a different lookback or check the
        metric list under <i>Workspace → Components</i>.
      </div>
    );
  }
  return (
    <div className="seo-perf-totals">
      <Kpi label="Visitors" value={compact(vs.visitors)} />
      <Kpi label="Unique visitors" value={compact(vs.unique_visitors)} />
      <Kpi
        label="Avg time on site"
        value={formatDuration(vs.avg_time_on_site_sec ?? 0)}
      />
      <Kpi
        label="Pages / visit"
        value={
          vs.pages_per_visit === undefined || vs.pages_per_visit === 0
            ? '—'
            : vs.pages_per_visit.toFixed(2)
        }
      />
      <Kpi
        label="Bounce rate"
        value={
          vs.bounce_rate === undefined
            ? '—'
            : `${((vs.bounce_rate > 1 ? vs.bounce_rate : vs.bounce_rate * 100) || 0).toFixed(1)}%`
        }
      />
      <Kpi label="Exits" value={compact(vs.exits)} />
    </div>
  );
}

function HourTable({ rows }: { rows: AdobeHourRow[] }) {
  if (rows.length === 0)
    return <div className="seo-empty">No hour-of-day data.</div>;
  const max = Math.max(...rows.map((r) => r.visits || 0)) || 1;
  // Sort by numeric hour ascending so 0 → 23 reads naturally.
  const ordered = [...rows].sort((a, b) => Number(a.hour) - Number(b.hour));
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>Hour</th>
          <th style={{ textAlign: 'right' }}>Visits</th>
          <th style={{ textAlign: 'right' }}>Share</th>
          <th style={{ width: 220 }}>&nbsp;</th>
        </tr>
      </thead>
      <tbody>
        {ordered.map((r) => (
          <tr key={r.hour}>
            <td>{r.hour}:00</td>
            <td className="seo-num">{r.visits.toLocaleString()}</td>
            <td className="seo-num">{r.share_pct.toFixed(1)}%</td>
            <td>
              <div className="seo-bar">
                <div
                  className="seo-bar-fill"
                  style={{
                    width: `${(r.visits / max) * 100}%`,
                    background: 'var(--accent)',
                  }}
                />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ExitPagesTable({ rows }: { rows: AdobeExitPageRow[] }) {
  if (rows.length === 0)
    return (
      <div className="seo-empty">
        No exit-page data — dimension may not be enabled or window is empty.
      </div>
    );
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Page</th>
          <th style={{ textAlign: 'right' }}>Exits</th>
          <th style={{ textAlign: 'right' }}>Exit rate</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const er = r.exit_rate > 1 ? r.exit_rate : r.exit_rate * 100;
          return (
            <tr key={r.item_id || `${r.page}-${i}`}>
              <td className="seo-num">{i + 1}</td>
              <td>{r.page || <i>(unset)</i>}</td>
              <td className="seo-num">{r.exits.toLocaleString()}</td>
              <td className="seo-num">{er.toFixed(1)}%</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SiteSectionsTable({ rows }: { rows: AdobeSiteSectionRow[] }) {
  if (rows.length === 0)
    return (
      <div className="seo-empty">
        No site-section data — depends on a Launch rule setting{' '}
        <code>variables/sitesection</code>. Pages roll up here if that
        rule is active.
      </div>
    );
  return (
    <ShareTable
      rows={rows.map((r) => ({
        label: r.section,
        count: r.visits,
        share: r.share_pct,
        meta: `${compact(r.page_views)} views`,
      }))}
      unit="Visits"
      emptyMsg=""
    />
  );
}

function NotFoundTable({ rows }: { rows: AdobeNotFoundRow[] }) {
  if (rows.length === 0)
    return (
      <div className="seo-empty">
        No page-not-found events — either the Launch rule for 404 tracking
        isn't firing, or there genuinely are no broken URLs in this window.
      </div>
    );
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>URL</th>
          <th style={{ textAlign: 'right' }}>Instances</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.url}-${i}`}>
            <td className="seo-num">{i + 1}</td>
            <td>{r.url || <i>(unset)</i>}</td>
            <td className="seo-num">{r.instances.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function InternalSearchTable({ rows }: { rows: AdobeInternalSearchRow[] }) {
  if (rows.length === 0)
    return (
      <div className="seo-empty">
        No internal-search data on this suite. Check that the eVar /
        prop holding the search term is named{' '}
        <code>variables/internalsearchterm(s)</code> — otherwise edit the
        adapter to point at the right one.
      </div>
    );
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Search term</th>
          <th style={{ textAlign: 'right' }}>Instances</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.item_id || `${r.term}-${i}`}>
            <td className="seo-num">{i + 1}</td>
            <td>{r.term || <i>(blank)</i>}</td>
            <td className="seo-num">{r.instances.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LeadEventsTable({ rows }: { rows: AdobeLeadEventRow[] }) {
  if (rows.length === 0)
    return (
      <div className="seo-empty">
        No lead-event data — either <code>ADOBE_LEAD_HASH_EVAR</code> is
        unset in the backend env, or the eVar has no values in this
        window. The adapter pulls the dimension itself (not a tied
        custom-event count); ask analytics for the event ID if you want
        per-lead totals.
      </div>
    );
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Hash value</th>
          <th style={{ textAlign: 'right' }}>Occurrences</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.hash_value}-${i}`}>
            <td className="seo-num">{i + 1}</td>
            <td>
              <code style={{ fontSize: 12 }}>{r.hash_value}</code>
            </td>
            <td className="seo-num">{r.occurrences.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CatalogueTable({
  rows,
  kind,
}: {
  rows: AdobeCatalogueItem[];
  kind: string;
}) {
  if (rows.length === 0)
    return (
      <div className="seo-empty">
        No {kind}s found in the workspace catalogue.
      </div>
    );
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Name</th>
          <th>Owner</th>
          <th>Type</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id || r.name}>
            <td>
              <code style={{ fontSize: 12 }}>{r.id}</code>
            </td>
            <td title={r.description}>{r.name}</td>
            <td style={{ color: 'var(--text-2)', fontSize: 12 }}>{r.owner}</td>
            <td style={{ color: 'var(--text-2)', fontSize: 12 }}>{r.type}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CacheAuditCard({
  cached,
}: {
  cached: Record<string, AdobeCachedSection>;
}) {
  const entries = Object.entries(cached);
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Cache audit</h2>
        <span className="seo-card-sub">
          {entries.length} cached sections on disk for this report suite — used
          as fall-back when a live Adobe call fails.
        </span>
      </div>
      {entries.length === 0 ? (
        <div className="seo-empty">
          No cache files yet — they'll appear after the first successful pull.
        </div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Section</th>
              <th style={{ textAlign: 'right' }}>Age</th>
              <th style={{ textAlign: 'right' }}>Lookback</th>
              <th style={{ textAlign: 'right' }}>Size</th>
            </tr>
          </thead>
          <tbody>
            {entries
              .sort((a, b) => (a[0] < b[0] ? -1 : 1))
              .map(([key, env]) => (
                <tr key={key}>
                  <td>{key}</td>
                  <td className="seo-num">
                    {env.age_sec === undefined || env.age_sec === null
                      ? '—'
                      : formatAge(env.age_sec)}
                  </td>
                  <td className="seo-num">
                    {env.lookback_days ? `${env.lookback_days}d` : '—'}
                  </td>
                  <td className="seo-num">
                    {env.size_bytes ? `${(env.size_bytes / 1024).toFixed(1)} KB` : '—'}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── existing reusable components, slightly trimmed ───────────────────

function ChannelsSection({ rows }: { rows: AdobeChannelRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="seo-empty">
        No marketing-channel data for this window.
      </div>
    );
  }
  const donutEntries = rows.slice(0, 8).map((r, i) => ({
    label: r.channel,
    count: r.visits,
    color: PALETTE[i % PALETTE.length],
  }));
  return (
    <div className="seo-channels-row">
      <MiniDonut
        entries={donutEntries}
        size={180}
        thickness={22}
        centerLabel="Channels"
      />
      <table className="seo-table seo-table-compact">
        <thead>
          <tr>
            <th>Channel</th>
            <th style={{ textAlign: 'right' }}>Visits</th>
            <th style={{ textAlign: 'right' }}>Share</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.channel}-${i}`}>
              <td>
                <span
                  className="seo-swatch"
                  style={{ background: PALETTE[i % PALETTE.length] }}
                />
                {r.channel || <i>(unset)</i>}
              </td>
              <td className="seo-num">{r.visits.toLocaleString()}</td>
              <td className="seo-num">{r.share_pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type SortKey = 'page' | 'page_views';

function TopPagesTable({ rows }: { rows: AdobeTopPageRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('page_views');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = sortKey === 'page' ? a.page : a.page_views;
      const bv = sortKey === 'page' ? b.page : b.page_views;
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const setSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k);
      setSortDir(k === 'page' ? 'asc' : 'desc');
    }
  };

  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th onClick={() => setSort('page')} style={{ cursor: 'pointer' }}>
            Page{sortKey === 'page' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </th>
          <th
            onClick={() => setSort('page_views')}
            style={{ cursor: 'pointer', textAlign: 'right' }}
          >
            Page views
            {sortKey === 'page_views' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r, idx) => (
          <tr key={r.item_id || `${r.page}-${idx}`}>
            <td className="seo-num">{idx + 1}</td>
            <td>{r.page || <i>(unset)</i>}</td>
            <td className="seo-num">{r.page_views.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EntryPagesTable({ rows }: { rows: AdobeEntryPageRow[] }) {
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Page</th>
          <th style={{ textAlign: 'right' }}>Entries</th>
          <th style={{ textAlign: 'right' }}>Bounce rate</th>
          <th style={{ textAlign: 'right' }}>Avg time</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, idx) => {
          const br = r.bounce_rate > 1 ? r.bounce_rate : r.bounce_rate * 100;
          return (
            <tr key={r.item_id || `${r.page}-${idx}`}>
              <td className="seo-num">{idx + 1}</td>
              <td>{r.page || <i>(unset)</i>}</td>
              <td className="seo-num">{r.entries.toLocaleString()}</td>
              <td className="seo-num">{br.toFixed(1)}%</td>
              <td className="seo-num">{formatDuration(r.time_on_page_sec)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ShareTable({
  rows,
  unit,
  emptyMsg,
}: {
  rows: { label: string; count: number; share: number; meta?: string }[];
  unit: string;
  emptyMsg: string;
}) {
  if (rows.length === 0) {
    return <div className="seo-empty">{emptyMsg}</div>;
  }
  const max = rows.reduce((m, r) => (r.count > m ? r.count : m), 0) || 1;
  return (
    <table className="seo-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Label</th>
          <th style={{ textAlign: 'right' }}>{unit}</th>
          <th style={{ textAlign: 'right' }}>Share</th>
          <th style={{ width: 220 }}>&nbsp;</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.label}-${i}`}>
            <td className="seo-num">{i + 1}</td>
            <td>
              {r.label || <i>(unset)</i>}
              {r.meta ? (
                <span style={{ color: 'var(--text-3)', marginLeft: 8, fontSize: 12 }}>
                  · {r.meta}
                </span>
              ) : null}
            </td>
            <td className="seo-num">{r.count.toLocaleString()}</td>
            <td className="seo-num">{r.share.toFixed(1)}%</td>
            <td>
              <div className="seo-bar">
                <div
                  className="seo-bar-fill"
                  style={{
                    width: `${(r.count / max) * 100}%`,
                    background: PALETTE[i % PALETTE.length],
                  }}
                />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Kpi({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="seo-kpi">
      <div className="seo-kpi-label">{label}</div>
      <div className="seo-kpi-value">{value ?? '—'}</div>
    </div>
  );
}

function compact(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (abs >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return Math.round(n).toLocaleString();
}

function formatDuration(sec: number | undefined): string {
  if (!sec || Number.isNaN(sec)) return '—';
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec - m * 60);
  return `${m}m ${s}s`;
}

function formatAge(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86400)}d`;
}
