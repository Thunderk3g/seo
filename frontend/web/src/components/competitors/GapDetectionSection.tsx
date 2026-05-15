// GapDetectionSection — the Phase-2 detection findings, now grouped
// into three logical sections inside the Competitors page's "Detection
// Findings" tab:
//
//   Visibility            — AI Visibility + SERP Visibility
//   Competitor Discovery  — Competitor Discovery (single, full-width)
//   Deep Audit            — Technical + Architecture + Content + Commercial
//
// Each group renders as its own .seo-card with a small head, and the
// agent cards sit inside in a 2-column responsive grid (reusing
// .seo-row-2-balanced). The single-card Discovery group spans full
// width naturally because only one cell renders.
//
// AgentFindingsCard itself is unchanged — same component, regrouped.

import { useCompetitorGap } from '../../api/hooks/useCompetitorGap';
import AgentFindingsCard from './AgentFindingsCard';

interface FindingGroup {
  id: string;
  label: string;
  sub: string;
  agents: string[];
}

const FINDING_GROUPS: FindingGroup[] = [
  {
    id: 'visibility',
    label: 'Visibility',
    sub: 'How discoverable we are on AI search + traditional SERP',
    agents: ['ai_visibility', 'serp_visibility'],
  },
  {
    id: 'discovery',
    label: 'Competitor Discovery',
    sub: 'Unified rival roster across AI, SERP, and SEMrush sources',
    agents: ['competitor_discovery'],
  },
  {
    id: 'audit',
    label: 'Deep Audit',
    sub: 'Technical / architectural / content / commercial signals',
    agents: [
      'technical_audit',
      'architecture_audit',
      'content_extractability',
      'product_commercial',
    ],
  },
];

export default function GapDetectionSection({ domain }: { domain?: string }) {
  const { data, isLoading, isError, error } = useCompetitorGap(
    domain || 'bajajlifeinsurance.com',
  );

  return (
    <div className="findings-tab">
      {isLoading && (
        <div className="seo-empty">Loading detection findings…</div>
      )}
      {isError && (
        <div className="seo-error">
          Failed to fetch detection findings:{' '}
          {error instanceof Error ? error.message : 'unknown error'}
        </div>
      )}
      {data && !data.available && (
        <div className="seo-empty">
          No completed grading run for this domain yet. Start one from the
          Assistant page or the top-bar Run Grade button.
        </div>
      )}

      {data && data.available && (
        <>
          {FINDING_GROUPS.map((group) => (
            <FindingsGroupCard
              key={group.id}
              group={group}
              findingsByAgent={data.findings_by_agent}
              agentStatus={data.agent_status}
            />
          ))}
        </>
      )}
    </div>
  );
}

function FindingsGroupCard({
  group,
  findingsByAgent,
  agentStatus,
}: {
  group: FindingGroup;
  findingsByAgent?: Record<string, import('../../api/seoTypes').DetectionFinding[]>;
  agentStatus?: Record<string, import('../../api/seoTypes').AgentStatus>;
}) {
  // Two-column responsive grid inside each group. Single-card groups
  // (Discovery) get a single full-width slot.
  const inner =
    group.agents.length === 1 ? (
      <AgentFindingsCard
        agent={group.agents[0]}
        findings={findingsByAgent?.[group.agents[0]] || []}
        status={agentStatus?.[group.agents[0]]}
      />
    ) : (
      <div className="findings-group-grid">
        {group.agents.map((agent) => (
          <AgentFindingsCard
            key={agent}
            agent={agent}
            findings={findingsByAgent?.[agent] || []}
            status={agentStatus?.[agent]}
          />
        ))}
      </div>
    );

  return (
    <div className="seo-card findings-group">
      <div className="seo-card-head">
        <h2>{group.label}</h2>
        <span className="seo-card-sub">{group.sub}</span>
      </div>
      {inner}
    </div>
  );
}
