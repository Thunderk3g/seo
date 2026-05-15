// Six-step interactive timeline. Doubles as the sub-tab nav for the
// Discovery Pipeline tab: clicking a step renders just that panel below.
//
// Stage states:
//   pending           — not started yet → button is disabled (clicks are no-ops)
//   running / ok /
//   skipped / empty /
//   failed / no_gaps  — interactive; click to focus that stage
//
// The currently-selected stage gets ``gap-pipe-step--active`` so the
// status badge colour (running / ok / failed) survives independently
// of the selected-tab indicator.

import type {
  GapPipelineRunHeader,
  GapStageName,
  GapStageStatus,
} from '../../../api/seoTypes';

const STAGES: { name: GapStageName; label: string; sub: string }[] = [
  {
    name: 'queries',
    label: 'Queries',
    sub: 'LLM-synthesised from your keywords',
  },
  {
    name: 'llm_search',
    label: 'LLM search',
    sub: 'ChatGPT / Claude / Gemini / Perplexity / Grok',
  },
  {
    name: 'serp_search',
    label: 'SERP search',
    sub: 'Google / Bing / DuckDuckGo',
  },
  {
    name: 'competitors',
    label: 'Top competitors',
    sub: 'Scored across LLM + SERP signals',
  },
  {
    name: 'deep_crawl',
    label: 'Deep crawl',
    sub: 'Profile each rival like we crawl ourselves',
  },
  {
    name: 'comparison',
    label: 'Gap comparison',
    sub: 'Where we lag the rival median',
  },
];

const STATUS_LABEL: Record<GapStageStatus, string> = {
  pending: 'queued',
  running: 'running…',
  ok: 'ok',
  skipped: 'skipped',
  failed: 'failed',
  empty: 'no data',
  no_gaps_found: 'no gaps',
};

function badgeClass(status: GapStageStatus): string {
  if (status === 'ok' || status === 'no_gaps_found') return 'ok';
  if (status === 'failed') return 'crashed';
  if (status === 'running') return 'ok';
  if (status === 'skipped' || status === 'empty') return 'skipped';
  return 'empty';
}

export default function StageTimeline({
  run,
  activeStage,
  onSelect,
}: {
  run: GapPipelineRunHeader;
  activeStage: GapStageName;
  onSelect: (stage: GapStageName) => void;
}) {
  return (
    <ol className="gap-pipe-timeline">
      {STAGES.map((stage, idx) => {
        const slot = run.stage_status?.[stage.name];
        const status: GapStageStatus = slot?.status ?? 'pending';
        const isActive = stage.name === activeStage;
        const isPending = status === 'pending';
        // Active modifier wins visually over the pending greying. Pending
        // is still disabled — you can't focus a stage that hasn't started.
        const modifier = [
          `gap-pipe-step--${status}`,
          isActive ? 'gap-pipe-step--active' : '',
        ]
          .filter(Boolean)
          .join(' ');
        return (
          <li key={stage.name} className={`gap-pipe-step ${modifier}`}>
            <button
              type="button"
              className="gap-pipe-step-btn"
              onClick={() => {
                if (!isPending) onSelect(stage.name);
              }}
              disabled={isPending}
              aria-pressed={isActive}
              aria-label={`Stage ${idx + 1}: ${stage.label} (${
                STATUS_LABEL[status]
              })`}
            >
              <div className="gap-pipe-step-index">{idx + 1}</div>
              <div className="gap-pipe-step-body">
                <div className="gap-pipe-step-title">{stage.label}</div>
                <div className="gap-pipe-step-sub">{stage.sub}</div>
                <span className={`gap-status-badge ${badgeClass(status)}`}>
                  {STATUS_LABEL[status]}
                </span>
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
