// IssueDistributionCard — donut + legend tile for the dashboard's row 2.
//
// Mirrors `.design-ref/project/dashboard.jsx` IssueDistributionCard (lines
// 57-89). Aggregates the IssueSummary[] payload from `useIssues` into three
// severity buckets (errors / warnings / notices) and feeds them to the
// MiniDonut primitive.
//
// Wave-1 ships MiniDonut with `entries: { label, count, color }[]` (NOT the
// design's `segments` prop), so we adapt to that signature and let the
// primitive own the centre label and animation.

import { useIssues } from '../../api/hooks/useIssues';
import MiniDonut from '../charts/MiniDonut';
import type { IssueSummary } from '../../api/types';

interface Props {
  sessionId: string | null;
}

const SEVERITY_COLOR = {
  error: '#f87171',
  warning: '#fbbf24',
  notice: '#60a5fa',
} as const;

const SEVERITY_LABEL = {
  error: 'Errors',
  warning: 'Warnings',
  notice: 'Notices',
} as const;

function bucket(items: IssueSummary[], severity: keyof typeof SEVERITY_COLOR) {
  return items
    .filter((i) => i.severity === severity)
    .reduce((sum, i) => sum + i.count, 0);
}

export default function IssueDistributionCard({ sessionId }: Props) {
  const issues = useIssues(sessionId);
  const items = issues.data ?? [];

  const errors = bucket(items, 'error');
  const warnings = bucket(items, 'warning');
  const notices = bucket(items, 'notice');
  const total = errors + warnings + notices;

  const entries = [
    { label: SEVERITY_LABEL.error, count: errors, color: SEVERITY_COLOR.error },
    { label: SEVERITY_LABEL.warning, count: warnings, color: SEVERITY_COLOR.warning },
    { label: SEVERITY_LABEL.notice, count: notices, color: SEVERITY_COLOR.notice },
  ];

  return (
    <div className="card">
      <div className="card-head">
        <h3>Issue distribution</h3>
        <a className="link-btn" href="#issues">View all</a>
      </div>

      {!sessionId && (
        <p className="text-muted" style={{ fontSize: 12 }}>
          No crawl session yet.
        </p>
      )}
      {sessionId && issues.isPending && (
        <p className="text-muted" style={{ fontSize: 12 }}>Loading…</p>
      )}
      {sessionId && issues.isError && (
        <p style={{ color: '#f87171', fontSize: 12 }}>
          Failed to load issues.
        </p>
      )}

      {sessionId && issues.data && (
        <div className="issue-dist-body">
          <MiniDonut
            entries={entries}
            total={total}
            size={140}
            thickness={14}
            centerLabel="Total issues"
          />
          <div className="issue-dist-list">
            {entries.map((e) => {
              const pct = total > 0 ? (e.count / total) * 100 : 0;
              return (
                <div key={e.label} className="issue-dist-row">
                  <span className="dot-sm" style={{ background: e.color }} />
                  <span className="issue-dist-label">{e.label}</span>
                  <span className="issue-dist-count">
                    {e.count.toLocaleString()}
                  </span>
                  <span className="issue-dist-pct">
                    {pct.toFixed(0)}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
