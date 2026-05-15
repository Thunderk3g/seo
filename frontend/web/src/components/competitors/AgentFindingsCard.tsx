// One card per detection agent — GSC/SEMrush-style disclosure block.
//
// Layout:
//   • The whole card head is a button. Click to collapse / expand the
//     body. A right-side caret (▸ / ▾) signals state. Default = expanded.
//   • Count chip on the right is plain neutral text — just the number.
//     No severity colour, no pastel pill.
//   • Each finding row is a flat title + description, separated from
//     the next by a 1 px hairline. No left colour bar, no severity pill.
//   • Severity is preserved as a small uppercase label in the row foot,
//     rendered in the same neutral grey as the rest of the foot text
//     (matches how GSC's Coverage report labels "Error / Warning / Valid").
//   • Evidence refs are nested behind a second disclosure: "View N
//     evidence items" expands a list of monospace chips below the foot.

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

type Variant = 'ok' | 'skipped' | 'crashed' | 'empty';

export default function AgentFindingsCard({
  agent,
  findings,
  status,
}: Props) {
  const [open, setOpen] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const meta = PRETTY_NAMES[agent] || { label: agent, sub: '' };
  const visible = expanded ? findings : findings.slice(0, 3);
  const hasMore = findings.length > visible.length;

  const variant: Variant = status?.status
    ? (status.status as Variant)
    : findings.length === 0
      ? 'empty'
      : 'ok';

  return (
    <div className={`seo-card gap-card gap-card-${variant} ${open ? 'gap-card-open' : 'gap-card-collapsed'}`}>
      <button
        type="button"
        className="gap-card-head-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="gap-card-head-meta">
          <div className="gap-card-title">{meta.label}</div>
          <div className="gap-card-sub">{meta.sub}</div>
        </div>
        <div className="gap-card-head-aside">
          <SummaryChip variant={variant} count={findings.length} />
          <span className="gap-card-caret" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
        </div>
      </button>

      {open && (
        <div className="gap-card-body">
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
            <div className="gap-card-empty">
              No weak points detected for this category.
            </div>
          ) : (
            <ul className="gap-card-findings">
              {visible.map((f) => (
                <FindingRow key={f.id} finding={f} />
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
      )}
    </div>
  );
}

function FindingRow({ finding }: { finding: DetectionFinding }) {
  const [showEvidence, setShowEvidence] = useState(false);
  const refs = finding.evidence_refs ?? [];
  return (
    <li className="gap-finding">
      <div className="gap-finding-title">{finding.title}</div>
      {finding.description && (
        <p className="gap-finding-desc">{finding.description}</p>
      )}
      <div className="gap-finding-foot">
        <span className="gap-sev-text">{labelFor(finding.severity)}</span>
        {refs.length > 0 && (
          <>
            <span className="gap-finding-foot-sep">·</span>
            <button
              type="button"
              className={`gap-finding-evidence-toggle ${
                showEvidence ? 'is-open' : ''
              }`}
              onClick={() => setShowEvidence((v) => !v)}
              aria-expanded={showEvidence}
            >
              {showEvidence ? 'Hide' : 'View'} {refs.length} evidence
              {refs.length === 1 ? ' item' : ' items'}
            </button>
          </>
        )}
      </div>
      {showEvidence && refs.length > 0 && (
        <div className="gap-finding-refs">
          {refs.slice(0, 8).map((r, i) => (
            <code key={i}>{r}</code>
          ))}
        </div>
      )}
    </li>
  );
}

function SummaryChip({
  variant,
  count,
}: {
  variant: Variant;
  count: number;
}) {
  if (variant === 'skipped') {
    return <span className="gap-status-text gap-status-skipped">Not configured</span>;
  }
  if (variant === 'crashed') {
    return <span className="gap-status-text gap-status-crashed">Error</span>;
  }
  if (variant === 'empty' || count === 0) {
    return <span className="gap-status-text gap-status-empty">No issues</span>;
  }
  return (
    <span className="gap-status-chip">
      <span className="gap-status-num">{count}</span>
      <span className="gap-status-label">
        {count === 1 ? 'finding' : 'findings'}
      </span>
    </span>
  );
}

function labelFor(severity: string): string {
  if (severity === 'critical') return 'CRITICAL';
  if (severity === 'warning') return 'WARNING';
  if (severity === 'notice') return 'NOTICE';
  return severity.toUpperCase();
}
