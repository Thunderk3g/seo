// One card per detection agent. Shows the agent name + status badge
// (clean, skipped, crashed, no-findings) plus the top three findings.
// Click "Show all N" to expand and see the rest.

import { useState } from 'react';
import type {
  AgentStatus,
  DetectionFinding,
} from '../../api/seoTypes';

const PRETTY_NAMES: Record<string, { label: string; sub: string }> = {
  ai_visibility: {
    label: 'AI Search Visibility',
    sub: 'ChatGPT / Claude / Gemini / Perplexity / Grok citations',
  },
  serp_visibility: {
    label: 'SERP Visibility',
    sub: 'Google / Bing / DuckDuckGo rankings + featured snippets',
  },
  competitor_discovery: {
    label: 'Competitor Discovery',
    sub: 'Unified competitor master list across all sources',
  },
  technical_audit: {
    label: 'Technical Audit',
    sub: 'Robots / sitemap / response times / structured data',
  },
  architecture_audit: {
    label: 'Architecture Audit',
    sub: 'URL breadth / click depth / breadcrumb / internal links',
  },
  content_extractability: {
    label: 'Content Extractability',
    sub: 'FAQ / stats / freshness / schema / author signals',
  },
  product_commercial: {
    label: 'Product & Commercial',
    sub: 'Pricing pages / calculators / comparisons / schema',
  },
};

interface Props {
  agent: string;
  findings: DetectionFinding[];
  status?: AgentStatus;
}

export default function AgentFindingsCard({
  agent,
  findings,
  status,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const meta = PRETTY_NAMES[agent] || { label: agent, sub: '' };
  const visible = expanded ? findings : findings.slice(0, 3);
  const hasMore = findings.length > visible.length;

  const variant = status?.status
    ? status.status
    : findings.length === 0
    ? 'empty'
    : 'ok';

  return (
    <div className={`seo-card gap-card gap-card-${variant}`}>
      <header className="gap-card-head">
        <div>
          <div className="gap-card-title">{meta.label}</div>
          <div className="gap-card-sub">{meta.sub}</div>
        </div>
        <StatusBadge variant={variant} count={findings.length} />
      </header>

      {status?.status === 'skipped' && (
        <div className="gap-card-skip">
          <strong>Skipped:</strong> {status.reason || 'unknown reason'}
        </div>
      )}
      {status?.status === 'crashed' && (
        <div className="gap-card-skip gap-card-crashed">
          <strong>Crashed:</strong> {status.reason || 'unknown reason'}
        </div>
      )}

      {findings.length === 0 && !status ? (
        <div className="gap-card-empty">No weak points detected for this category.</div>
      ) : (
        <ul className="gap-card-findings">
          {visible.map((f) => (
            <li key={f.id} className={`gap-finding sev-${f.severity}`}>
              <div className="gap-finding-head">
                <span className={`gap-sev sev-${f.severity}`}>{f.severity}</span>
                <span className="gap-finding-title">{f.title}</span>
              </div>
              {f.description && (
                <p className="gap-finding-desc">{f.description}</p>
              )}
              {f.evidence_refs?.length > 0 && (
                <div className="gap-finding-refs">
                  {f.evidence_refs.slice(0, 4).map((r, i) => (
                    <code key={i}>{r}</code>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {hasMore && (
        <button
          type="button"
          className="gap-card-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded
            ? 'Show top 3'
            : `Show all ${findings.length} findings`}
        </button>
      )}
    </div>
  );
}

function StatusBadge({
  variant,
  count,
}: {
  variant: 'ok' | 'skipped' | 'crashed' | 'empty';
  count: number;
}) {
  if (variant === 'skipped') {
    return <span className="gap-status-badge skipped">Not configured</span>;
  }
  if (variant === 'crashed') {
    return <span className="gap-status-badge crashed">Error</span>;
  }
  if (variant === 'empty') {
    return <span className="gap-status-badge empty">No data</span>;
  }
  return <span className="gap-status-badge ok">{count} finding{count === 1 ? '' : 's'}</span>;
}
