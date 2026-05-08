// TopIssuesCard — top-8 issues sorted by occurrence count.
//
// Mirrors `.design-ref/project/dashboard.jsx` TopIssuesCard (lines
// 145-165). Reuses `useIssues` (same query key as IssueDistributionCard,
// so TanStack Query dedupes the fetch).

import { useIssues } from '../../api/hooks/useIssues';

interface Props {
  sessionId: string | null;
}

export default function TopIssuesCard({ sessionId }: Props) {
  const issues = useIssues(sessionId);
  const items = issues.data ?? [];

  const top = items
    .filter((i) => i.count > 0)
    .slice()
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

  return (
    <div className="card">
      <div className="card-head">
        <h3>Top issues</h3>
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
      {sessionId && issues.data && top.length === 0 && (
        <p className="text-muted" style={{ fontSize: 12 }}>
          No issues detected — clean crawl.
        </p>
      )}

      {top.length > 0 && (
        <div className="top-issues">
          {top.map((i) => (
            <div key={i.id} className="top-issue-row">
              <span className={'sev-dot sev-' + i.severity} />
              <span className="top-issue-name">{i.name}</span>
              <span className="top-issue-count">
                {i.count.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
