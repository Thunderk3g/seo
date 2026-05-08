// IssuesPage — derived issues list + detail panel for the active site's
// latest crawl session.
//
// Layout ported from .design-ref/project/pages.jsx (IssuesPage component):
//   PageHeader • two-column .issues-row:
//     LEFT  .issues-list-card  — severity tabs + scrolling issue list
//     RIGHT .issue-detail-card — selected issue's description + affected URLs
//
// Behaviour cuts (per spec §5.4.4): "Copy list", "Export", and "Configure
// rules" buttons are CUT in v1 — Export lands on Day 4. The page renders
// just the list and detail; no action buttons.
//
// The severity filter is a client-side filter over the IssueSummary[]
// payload (small list, ~12 categories) — the backend doesn't expose a
// severity query param.

import { useState } from 'react';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useIssues, useIssueDetail } from '../api/hooks/useIssues';
import type { IssueSeverity, IssueSummary } from '../api/types';
import PageHeader from '../components/PageHeader';
import Icon from '../components/icons/Icon';

type SevFilter = 'all' | IssueSeverity;

const SEV_TABS: { id: SevFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'error', label: 'Errors' },
  { id: 'warning', label: 'Warnings' },
  { id: 'notice', label: 'Notices' },
];

function totalIssueCount(items: IssueSummary[] | undefined): number {
  if (!items) return 0;
  return items.reduce((sum, i) => sum + i.count, 0);
}

export default function IssuesPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Use the most recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;
  const sessionId = session?.id ?? null;

  const issuesQuery = useIssues(sessionId);
  const [sevFilter, setSevFilter] = useState<SevFilter>('all');
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);

  const allIssues = issuesQuery.data ?? [];
  const filtered =
    sevFilter === 'all'
      ? allIssues
      : allIssues.filter((i) => i.severity === sevFilter);

  // Auto-select the first visible issue if the user hasn't picked one yet
  // (or the previously selected one is no longer in the filtered set).
  const selectedInFiltered = filtered.find((i) => i.id === selectedIssueId);
  const effectiveSelectedId =
    selectedInFiltered?.id ?? filtered[0]?.id ?? null;

  const detailQuery = useIssueDetail(sessionId, effectiveSelectedId);

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (!session) return 'No crawl sessions yet — start one from the topbar';
    if (issuesQuery.isPending) return 'Loading issues…';
    const total = totalIssueCount(issuesQuery.data);
    const cats = allIssues.length;
    return `${total.toLocaleString()} ${total === 1 ? 'issue' : 'issues'} across ${cats} ${cats === 1 ? 'category' : 'categories'}`;
  })();

  return (
    <div className="page-grid">
      <PageHeader title="Issues" subtitle={subtitle} />

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to see issues.
          </p>
        </div>
      )}

      {activeSiteId && !session && !sessionsQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No crawl sessions exist for this site yet. Start one from the
            topbar to surface issues.
          </p>
        </div>
      )}

      {session && issuesQuery.isError && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p style={{ color: 'var(--error, #f87171)' }}>
            Failed to load issues
            {issuesQuery.error instanceof Error
              ? `: ${issuesQuery.error.message}`
              : '.'}
          </p>
        </div>
      )}

      {session && issuesQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">Loading issues…</p>
        </div>
      )}

      {session && issuesQuery.data && allIssues.length === 0 && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No issues detected for this session. Nice.
          </p>
        </div>
      )}

      {session && issuesQuery.data && allIssues.length > 0 && (
        <div className="row issues-row">
          {/* LEFT — issue list with severity tabs */}
          <div className="card issues-list-card">
            <div className="card-head card-head-flex">
              <h3>All issues</h3>
              <div className="tabs small">
                {SEV_TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={'tab ' + (t.id === sevFilter ? 'active' : '')}
                    onClick={() => setSevFilter(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="issues-list">
              {filtered.length === 0 && (
                <div style={{ padding: 14 }}>
                  <p className="text-muted">No issues match this filter.</p>
                </div>
              )}
              {filtered.map((issue) => {
                const isActive = issue.id === effectiveSelectedId;
                const isEmpty = issue.count === 0;
                return (
                  <button
                    key={issue.id}
                    type="button"
                    className={'issue-list-item ' + (isActive ? 'active' : '')}
                    onClick={() => setSelectedIssueId(issue.id)}
                    style={isEmpty ? { color: 'var(--text-3)' } : undefined}
                  >
                    <span className={'sev-bar sev-' + issue.severity} />
                    <div className="issue-list-body">
                      <div className="issue-list-head">
                        <span
                          className="issue-list-name"
                          style={isEmpty ? { color: 'var(--text-3)' } : undefined}
                        >
                          {issue.name}
                        </span>
                        <span
                          className="issue-list-count"
                          style={isEmpty ? { color: 'var(--text-3)' } : undefined}
                        >
                          {issue.count.toLocaleString()}
                        </span>
                      </div>
                      <div className="issue-list-desc">{issue.description}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* RIGHT — selected issue detail */}
          <div className="card issue-detail-card">
            {!effectiveSelectedId && (
              <div style={{ padding: 'var(--pad)' }}>
                <p className="text-muted">Select an issue to see affected URLs.</p>
              </div>
            )}

            {effectiveSelectedId && detailQuery.isPending && (
              <div style={{ padding: 'var(--pad)' }}>
                <p className="text-muted">Loading issue detail…</p>
              </div>
            )}

            {effectiveSelectedId && detailQuery.isError && (
              <div style={{ padding: 'var(--pad)' }}>
                <p style={{ color: 'var(--error, #f87171)' }}>
                  Failed to load issue detail
                  {detailQuery.error instanceof Error
                    ? `: ${detailQuery.error.message}`
                    : '.'}
                </p>
              </div>
            )}

            {detailQuery.data && (
              <>
                <div className="issue-detail-head">
                  <div>
                    <div className="issue-detail-eyebrow">
                      <span className={'sev-pill sev-' + detailQuery.data.severity}>
                        {detailQuery.data.severity}
                      </span>
                      <span className="text-muted">·</span>
                      <span className="text-muted">
                        {detailQuery.data.affected_urls.length.toLocaleString()}{' '}
                        affected URL
                        {detailQuery.data.affected_urls.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <h2 className="issue-detail-title">{detailQuery.data.name}</h2>
                    <p className="issue-detail-desc">
                      {detailQuery.data.description}
                    </p>
                  </div>
                </div>

                <div className="issue-affected">
                  <div className="issue-affected-head">
                    <span>URL</span>
                    <span>Status</span>
                    <span>Depth</span>
                    <span>Resp.</span>
                    <span></span>
                  </div>
                  <div className="issue-affected-list">
                    {detailQuery.data.affected_urls.length === 0 && (
                      <div style={{ padding: 14 }}>
                        <p className="text-muted">No affected URLs.</p>
                      </div>
                    )}
                    {detailQuery.data.affected_urls.slice(0, 50).map((u) => {
                      const statusBucket =
                        u.http_status_code != null
                          ? Math.floor(u.http_status_code / 100)
                          : null;
                      return (
                        <div key={u.url} className="issue-affected-row">
                          <div
                            className="issue-affected-url"
                            title={u.url}
                          >
                            {u.url}
                          </div>
                          <div>
                            {u.http_status_code != null ? (
                              <span className={'status-pill s' + statusBucket}>
                                {u.http_status_code}
                              </span>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </div>
                          <div className="num">{u.crawl_depth}</div>
                          <div className="num">
                            {u.load_time_ms != null
                              ? `${Math.round(u.load_time_ms)}ms`
                              : '—'}
                          </div>
                          <div>
                            <a
                              href={u.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="icon-btn"
                              title="Open URL"
                            >
                              <Icon name="external" size={12} />
                            </a>
                          </div>
                        </div>
                      );
                    })}
                    {detailQuery.data.affected_urls.length > 50 && (
                      <div className="issue-affected-more">
                        +{' '}
                        {(
                          detailQuery.data.affected_urls.length - 50
                        ).toLocaleString()}{' '}
                        more affected URLs
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
