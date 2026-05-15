// CompetitorsPage — GSC-style tabbed view that unifies three competitor
// data sources behind one page header + KPI strip:
//
//   1. Overview            — legacy SEMrush competitor dashboard
//                            (roster + topic / keyword / hygiene / volume gaps).
//   2. Discovery Pipeline  — the Phase-3 transparent multi-stage flow
//                            (queries → LLM search → SERP → top-10 →
//                            deep crawl → comparison).
//   3. Detection Findings  — the seven Phase-2 detection agents grouped
//                            into Visibility / Discovery / Deep Audit.
//
// All three child hooks (useCompetitorDashboard, useLatestGapPipeline,
// useCompetitorGap) are fetched at page level so:
//   • The unified KPI strip can compose signals across all three sources.
//   • React Query keeps the data warm across tab switches (no refetch
//     when the user toggles tabs).
//   • Pipeline polling continues even when the user is on a different
//     tab.

import { useState } from 'react';
import { useCompetitorDashboard } from '../api/hooks/useCompetitorDashboard';
import { useCompetitorGap } from '../api/hooks/useCompetitorGap';
import { useLatestGapPipeline } from '../api/hooks/useGapPipeline';
import CompetitorOverviewTab from '../components/competitors/CompetitorOverviewTab';
import GapDetectionPipelineSection from '../components/competitors/GapDetectionPipelineSection';
import GapDetectionSection from '../components/competitors/GapDetectionSection';
import UnifiedKpiStrip from '../components/competitors/UnifiedKpiStrip';

type TabId = 'overview' | 'pipeline' | 'findings';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

export default function CompetitorsPage() {
  const dashboard = useCompetitorDashboard();
  const pipeline = useLatestGapPipeline(
    dashboard.data?.domain || DEFAULT_DOMAIN,
  );
  const findings = useCompetitorGap(dashboard.data?.domain || DEFAULT_DOMAIN);

  const [tab, setTab] = useState<TabId>('overview');

  // Counts shown on the tab pills. Each falls back gracefully to '·'
  // while data loads so the chip never renders empty.
  const rivalsCount = dashboard.data?.available
    ? dashboard.data.summary?.competitors_analysed ?? 0
    : pipeline.data?.available
      ? pipeline.data.competitor_count ?? 0
      : 0;
  const pipelineCount = pipeline.data?.available
    ? (pipeline.data.llm_call_count ?? 0) + (pipeline.data.serp_call_count ?? 0)
    : 0;
  const findingsCount = findings.data?.available
    ? Object.values(findings.data.findings_by_agent || {}).reduce(
        (acc, arr) => acc + (arr?.length ?? 0),
        0,
      )
    : 0;

  const domain = dashboard.data?.domain || DEFAULT_DOMAIN;

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Competitor Gap</h1>
          <div className="seo-page-sub">
            Three lenses on how <b>{domain}</b> stacks up: legacy SEMrush
            roster + topic gaps, a live multi-LLM + SERP discovery
            pipeline, and the seven-agent detection layer. Switch tabs to
            drill into each.
          </div>
        </div>
      </header>

      <UnifiedKpiStrip
        dashboard={dashboard.data}
        pipeline={pipeline.data}
        findings={findings.data}
      />

      <div className="competitor-tab-strip">
        <button
          type="button"
          className={'tab ' + (tab === 'overview' ? 'active' : '')}
          onClick={() => setTab('overview')}
        >
          Overview{' '}
          <span className="tab-count">{rivalsCount.toLocaleString()}</span>
        </button>
        <button
          type="button"
          className={'tab ' + (tab === 'pipeline' ? 'active' : '')}
          onClick={() => setTab('pipeline')}
        >
          Discovery Pipeline{' '}
          <span className="tab-count">{pipelineCount.toLocaleString()}</span>
        </button>
        <button
          type="button"
          className={'tab ' + (tab === 'findings' ? 'active' : '')}
          onClick={() => setTab('findings')}
        >
          Detection Findings{' '}
          <span className="tab-count">{findingsCount.toLocaleString()}</span>
        </button>
      </div>

      <div className="competitor-tab-body">
        {tab === 'overview' && <OverviewTabBody />}
        {tab === 'pipeline' && (
          <GapDetectionPipelineSection domain={domain} />
        )}
        {tab === 'findings' && <GapDetectionSection domain={domain} />}
      </div>
    </div>
  );
}

function OverviewTabBody() {
  const { data, isLoading, isError, error } = useCompetitorDashboard();
  if (isLoading) {
    return (
      <div className="seo-empty">
        Building the competitor gap report. First-run can take 3–7
        minutes (SEMrush pulls + polite crawl of ~500 rival pages at
        1 req/sec). Cached for 7 days after that.
      </div>
    );
  }
  if (isError) {
    return (
      <div className="seo-error">
        Failed to fetch competitor data:{' '}
        {error instanceof Error ? error.message : 'unknown error'}
      </div>
    );
  }
  if (data && !data.available) {
    return (
      <div className="seo-empty">
        Competitor analysis is unavailable.{' '}
        {data.error ? <span>({data.error})</span> : null}
        {' '}Set <b>SEMRUSH_API_KEY</b> and{' '}
        <b>COMPETITOR_ENABLED=true</b> to enable.
      </div>
    );
  }
  if (!data) return null;
  return <CompetitorOverviewTab data={data} />;
}
