// GapDetectionPipelineSection — Phase-3 transparent gap detection pipeline.
// Now wrapped inside the Competitors page's "Discovery Pipeline" tab.
//
// Layout inside the tab:
//   1. Slim header row — header stats on the left, "Run pipeline" CTA on
//      the right. No duplicate page title (the page tab strip already
//      carries the section name).
//   2. Stage timeline — six clickable steps doubling as sub-tab nav.
//   3. Active panel — only the focused stage's panel renders.
//
// The polling lifecycle (status query + detail query) stays at this
// component level, unchanged, so polling continues even while a sibling
// tab is the visible one (the section stays mounted via React Query's
// page-level data sharing).

import { useEffect, useState } from 'react';
import {
  useGapPipelineDetail,
  useGapPipelineStatus,
  useLatestGapPipeline,
  useStartGapPipeline,
} from '../../api/hooks/useGapPipeline';
import type {
  GapPipelineRunHeader,
  GapStageName,
} from '../../api/seoTypes';
import ComparisonPanel from './pipeline/ComparisonPanel';
import DeepCrawlPanel from './pipeline/DeepCrawlPanel';
import LLMResultsPanel from './pipeline/LLMResultsPanel';
import QueriesPanel from './pipeline/QueriesPanel';
import SerpResultsPanel from './pipeline/SerpResultsPanel';
import StageTimeline from './pipeline/StageTimeline';
import TopCompetitorsPanel from './pipeline/TopCompetitorsPanel';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';
const ALL_STAGES: GapStageName[] = [
  'queries',
  'llm_search',
  'serp_search',
  'competitors',
  'deep_crawl',
  'comparison',
];

export default function GapDetectionPipelineSection({
  domain,
}: {
  domain?: string;
}) {
  const effectiveDomain = domain || DEFAULT_DOMAIN;
  const latest = useLatestGapPipeline(effectiveDomain);
  // After a successful start mutation we hold the new run id locally so
  // we don't have to wait for the latest-run query to refresh.
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const start = useStartGapPipeline();

  const resolvedRunId =
    activeRunId ||
    (latest.data?.available && latest.data.id ? latest.data.id : null);
  const statusQuery = useGapPipelineStatus(resolvedRunId || undefined);
  const detailQuery = useGapPipelineDetail(resolvedRunId || undefined);

  const run = statusQuery.data;
  const detail = detailQuery.data;
  const isRunning = run && run.status === 'running';
  const isPending = run && run.status === 'pending';

  // Active sub-stage state + auto-default based on what's available.
  const [activeStage, setActiveStage] = useState<GapStageName>('queries');
  const fingerprint = stageFingerprint(run);
  useEffect(() => {
    if (!run) return;
    const next = pickDefaultStage(run);
    // Only auto-advance when the user hasn't manually picked a stage that
    // *is still* a sensible target. If they're sitting on a finished stage
    // and a later one finishes, we move them forward — the auto-default
    // function returns the latest-meaningful stage.
    setActiveStage((current) => {
      const currentStatus = run.stage_status?.[current]?.status;
      const userSittingOnPending = currentStatus === 'pending';
      if (userSittingOnPending) return next;
      return current;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status, fingerprint]);

  const handleRun = () => {
    start.mutate(
      { domain: effectiveDomain },
      {
        onSuccess: (data) => {
          setActiveRunId(data.id);
          setActiveStage('queries');
        },
      },
    );
  };

  return (
    <div className="gap-pipe-tab">
      <div className="gap-pipe-tab-head">
        <div className="gap-pipe-tab-head-left">
          {run ? (
            <PipelineHeaderStats run={run} />
          ) : (
            <div className="seo-card-sub">
              No pipeline run yet for <b>{effectiveDomain}</b>.
            </div>
          )}
        </div>
        <button
          type="button"
          className="seo-btn"
          onClick={handleRun}
          disabled={
            start.isPending || Boolean(isRunning) || Boolean(isPending)
          }
          title={
            isRunning ? 'Pipeline already running' : 'Kick off a new run'
          }
        >
          {start.isPending
            ? 'Starting…'
            : isRunning
              ? 'Pipeline running…'
              : run
                ? 'Re-run pipeline'
                : 'Run pipeline'}
        </button>
      </div>

      {start.isError && (
        <div className="seo-error">
          Failed to start pipeline:{' '}
          {start.error instanceof Error
            ? start.error.message
            : 'unknown error'}
        </div>
      )}

      {latest.isLoading && !run && (
        <div className="seo-empty">Looking for a recent pipeline run…</div>
      )}

      {!resolvedRunId && !latest.isLoading && (
        <div className="seo-empty">
          Click <b>Run pipeline</b> to start one. First run takes
          ~3–6 min (LLM probes + SERP calls + crawl of 10 rival sites).
        </div>
      )}

      {run && (
        <StageTimeline
          run={run}
          activeStage={activeStage}
          onSelect={setActiveStage}
        />
      )}

      {run && detail && (
        <div className="gap-pipe-panel-wrap">
          {activeStage === 'queries' && (
            <QueriesPanel
              queries={detail.queries}
              seedKeywordCount={run.seed_keyword_count}
            />
          )}
          {activeStage === 'llm_search' && (
            <LLMResultsPanel
              results={detail.llm_results}
              queries={detail.queries}
            />
          )}
          {activeStage === 'serp_search' && (
            <SerpResultsPanel
              results={detail.serp_results}
              queries={detail.queries}
            />
          )}
          {activeStage === 'competitors' && (
            <TopCompetitorsPanel rows={detail.competitors} />
          )}
          {activeStage === 'deep_crawl' && (
            <DeepCrawlPanel rows={detail.deep_crawls} />
          )}
          {activeStage === 'comparison' && (
            <ComparisonPanel rows={detail.comparisons} />
          )}
        </div>
      )}

      {run && !detail && detailQuery.isLoading && (
        <div className="seo-empty">Loading pipeline data…</div>
      )}
      {detailQuery.isError && (
        <div className="seo-error">
          Failed to load pipeline detail:{' '}
          {detailQuery.error instanceof Error
            ? detailQuery.error.message
            : 'unknown error'}
        </div>
      )}
    </div>
  );
}

function PipelineHeaderStats({ run }: { run: GapPipelineRunHeader }) {
  return (
    <div className="gap-pipe-header-stats">
      <Stat label="Status" value={run.status} />
      <Stat label="Queries" value={run.query_count.toString()} />
      <Stat
        label="LLM calls"
        value={`${run.llm_call_count} · ${run.llm_provider_count} prov`}
      />
      <Stat
        label="SERP calls"
        value={`${run.serp_call_count} · ${run.serp_engine_count} eng`}
      />
      <Stat label="Competitors" value={run.competitor_count.toString()} />
      <Stat label="Pages crawled" value={run.deep_crawl_pages.toString()} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="gap-pipe-stat">
      <div className="gap-pipe-stat-label">{label}</div>
      <div className="gap-pipe-stat-value">{value}</div>
    </div>
  );
}

/** Default sub-stage selection rule:
 *
 *   1. If `comparison` finished `ok` or `no_gaps_found`, jump there —
 *      that's the answer the rest of the pipeline builds up to.
 *   2. Else, the *latest* stage that's at least `running` (so the user
 *      lands on whatever the pipeline is actively producing).
 *   3. Else, the first stage. */
function pickDefaultStage(run: GapPipelineRunHeader): GapStageName {
  const ss = run.stage_status || {};
  const cmp = ss.comparison?.status;
  if (cmp === 'ok' || cmp === 'no_gaps_found') return 'comparison';
  // Walk backwards so we find the latest interesting stage.
  for (let i = ALL_STAGES.length - 1; i >= 0; i--) {
    const name = ALL_STAGES[i];
    const s = ss[name]?.status;
    if (
      s === 'running' ||
      s === 'ok' ||
      s === 'no_gaps_found' ||
      s === 'failed' ||
      s === 'empty' ||
      s === 'skipped'
    ) {
      return name;
    }
  }
  return 'queries';
}

/** Compact fingerprint of every stage's status so the auto-default
 *  effect only re-fires when a status actually changes (avoids a render
 *  storm during the 3-second poll). */
function stageFingerprint(run?: GapPipelineRunHeader): string {
  if (!run) return '';
  return ALL_STAGES.map(
    (s) => `${s}:${run.stage_status?.[s]?.status ?? '-'}`,
  ).join('|');
}
