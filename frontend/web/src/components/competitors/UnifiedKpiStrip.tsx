// UnifiedKpiStrip — the one-glance answer at the top of the Competitors
// page. Combines signals from three data sources so the user sees the
// big numbers before drilling into any tab:
//
//   1. Competitor count   — from useCompetitorDashboard (SEMrush + crawl),
//                           falling back to the latest pipeline run's
//                           competitor_count if the dashboard is unavailable.
//   2. LLM mention %      — share of GapLLMResult rows where our brand
//                           was mentioned. Derived from the pipeline run
//                           when present; otherwise blank.
//   3. SERP top-10 %      — share of GapSerpResult rows where our_position
//                           is non-null. Same derivation rules.
//   4. Gap findings       — sum of detection findings across the seven
//                           Phase-2 agents (useCompetitorGap).
//   5. Last pipeline run  — relative age of the most recent pipeline run.
//   6. Pipeline status    — coloured badge (ok / running / failed / never).
//
// All cells degrade gracefully to "—" while data loads, so the strip
// never renders empty space on first paint.

import type {
  CompetitorDashboard,
  CompetitorGapResponse,
  GapPipelineLatest,
  GapPipelineStatus,
} from '../../api/seoTypes';

interface Props {
  dashboard?: CompetitorDashboard;
  pipeline?: GapPipelineLatest;
  findings?: CompetitorGapResponse;
}

const STATUS_LABEL: Record<GapPipelineStatus | 'never', string> = {
  pending: 'queued',
  running: 'running',
  complete: 'ok',
  degraded: 'partial',
  failed: 'failed',
  never: 'no runs',
};

const STATUS_TONE: Record<
  GapPipelineStatus | 'never',
  'ok' | 'warning' | 'error' | 'idle'
> = {
  pending: 'warning',
  running: 'warning',
  complete: 'ok',
  degraded: 'warning',
  failed: 'error',
  never: 'idle',
};

const TONE_VAR: Record<'ok' | 'warning' | 'error' | 'idle', string> = {
  ok: 'var(--accent)',
  warning: 'var(--warning, #b8860b)',
  error: 'var(--error, #b91c1c)',
  idle: 'var(--text-3)',
};

export default function UnifiedKpiStrip({
  dashboard,
  pipeline,
  findings,
}: Props) {
  const rivals = pickRivalCount(dashboard, pipeline);
  const llmMention = pickLlmMentionPct(findings, pipeline);
  const serpTop10 = pickSerpTop10Pct(findings, pipeline);
  const gaps = pickGapCount(findings);
  const lastRunAt = pickLastRunAt(pipeline);
  const status: GapPipelineStatus | 'never' = pipeline?.available
    ? (pipeline.status as GapPipelineStatus) ?? 'never'
    : 'never';

  return (
    <div className="seo-card seo-perf-card">
      <div className="seo-card-head">
        <h2>Competitor signals</h2>
        <span className="seo-card-sub">
          Cross-source snapshot · SEMrush + AI/SERP visibility + pipeline
        </span>
      </div>
      <div className="seo-perf-totals">
        <Kpi label="Rivals discovered" value={fmtInt(rivals)} />
        <Kpi label="LLM mentions" value={fmtPct(llmMention)} />
        <Kpi label="SERP top-10" value={fmtPct(serpTop10)} />
        <Kpi label="Gap findings" value={fmtInt(gaps)} />
        <Kpi label="Last run" value={lastRunAt} />
        <KpiBadge
          label="Pipeline"
          value={STATUS_LABEL[status]}
          tone={STATUS_TONE[status]}
        />
      </div>
    </div>
  );
}

function pickRivalCount(
  dashboard?: CompetitorDashboard,
  pipeline?: GapPipelineLatest,
): number | undefined {
  if (dashboard?.available && dashboard.summary) {
    return dashboard.summary.competitors_analysed;
  }
  if (pipeline?.available && typeof pipeline.competitor_count === 'number') {
    return pipeline.competitor_count;
  }
  return undefined;
}

function pickLlmMentionPct(
  findings?: CompetitorGapResponse,
  pipeline?: GapPipelineLatest,
): number | undefined {
  // Prefer the pipeline's stage_status data when present — it carries
  // a real mention rate computed in the comparison stage. Fall back to
  // counting "ai_visibility_overall" findings against priority queries
  // when we only have the legacy detection layer to go on.
  const stage = pipeline?.stage_status?.comparison?.data as
    | { llm_visibility?: { rate?: number; total?: number; mentioned?: number } }
    | undefined;
  if (stage?.llm_visibility?.rate !== undefined) {
    return stage.llm_visibility.rate * 100;
  }
  const rows = findings?.findings_by_agent?.ai_visibility ?? [];
  // The legacy agent encodes overall rate in evidence_refs like
  // "ai_visibility:rate=0.12" — pull from the first matching row.
  for (const f of rows) {
    for (const ref of f.evidence_refs ?? []) {
      const m = /^ai_visibility:rate=([0-9.]+)/.exec(ref);
      if (m) return Math.round(parseFloat(m[1]) * 1000) / 10;
    }
  }
  return undefined;
}

function pickSerpTop10Pct(
  findings?: CompetitorGapResponse,
  pipeline?: GapPipelineLatest,
): number | undefined {
  const stage = pipeline?.stage_status?.comparison?.data as
    | { serp_visibility?: { rate?: number } }
    | undefined;
  if (stage?.serp_visibility?.rate !== undefined) {
    return stage.serp_visibility.rate * 100;
  }
  // Legacy fallback: agent encodes per-engine rate in evidence_refs.
  // We average across whatever engines come back.
  const rows = findings?.findings_by_agent?.serp_visibility ?? [];
  const samples: number[] = [];
  for (const f of rows) {
    for (const ref of f.evidence_refs ?? []) {
      const m = /^serp_visibility:[a-z]+\.top10_rate=([0-9.]+)/.exec(ref);
      if (m) samples.push(parseFloat(m[1]));
    }
  }
  if (samples.length === 0) return undefined;
  const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
  return Math.round(avg * 1000) / 10;
}

function pickGapCount(findings?: CompetitorGapResponse): number | undefined {
  if (!findings?.available || !findings.findings_by_agent) return undefined;
  return Object.values(findings.findings_by_agent).reduce(
    (acc, arr) => acc + (arr?.length ?? 0),
    0,
  );
}

function pickLastRunAt(pipeline?: GapPipelineLatest): string {
  if (!pipeline?.available || !pipeline.started_at) return '—';
  return relativeAge(pipeline.started_at);
}

function relativeAge(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const diffSec = Math.max(0, (Date.now() - t) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.round(diffSec / 60)} min ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)} h ago`;
  return `${Math.round(diffSec / 86400)} d ago`;
}

function fmtInt(n?: number): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '—';
  return n.toLocaleString();
}

function fmtPct(n?: number): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '—';
  return `${n.toFixed(0)}%`;
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="seo-perf-total">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

function KpiBadge({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'ok' | 'warning' | 'error' | 'idle';
}) {
  return (
    <div className="seo-perf-total">
      <span className="label">{label}</span>
      <span
        className="value"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          color: TONE_VAR[tone],
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: TONE_VAR[tone],
            display: 'inline-block',
          }}
        />
        {value}
      </span>
    </div>
  );
}
