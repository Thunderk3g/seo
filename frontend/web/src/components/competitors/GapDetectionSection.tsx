// GapDetectionSection — the 7-card grid surfaced beneath the existing
// CompetitorsPage rosters. Renders one card per detection agent. The
// grid stays usable even when most agents are skipped (missing API
// keys) — those cards just show a muted "not configured" badge.

import { useCompetitorGap } from '../../api/hooks/useCompetitorGap';
import AgentFindingsCard from './AgentFindingsCard';

const DETECTION_AGENTS: string[] = [
  'ai_visibility',
  'serp_visibility',
  'competitor_discovery',
  'technical_audit',
  'architecture_audit',
  'content_extractability',
  'product_commercial',
];

export default function GapDetectionSection({ domain }: { domain?: string }) {
  const { data, isLoading, isError, error } = useCompetitorGap(
    domain || 'bajajlifeinsurance.com',
  );

  return (
    <section className="gap-section">
      <header className="gap-section-head">
        <div>
          <h2>Gap Detection</h2>
          <div className="gap-section-sub">
            Detection-only findings from the AI Visibility, SERP Visibility,
            and deep-audit agents. Fix recommendations ship in a later
            iteration; for now this surfaces <em>what to look at</em>.
          </div>
        </div>
      </header>

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
        <div className="gap-grid">
          {DETECTION_AGENTS.map((agent) => (
            <AgentFindingsCard
              key={agent}
              agent={agent}
              findings={data.findings_by_agent?.[agent] || []}
              status={data.agent_status?.[agent]}
            />
          ))}
        </div>
      )}
    </section>
  );
}
