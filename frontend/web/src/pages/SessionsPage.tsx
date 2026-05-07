// SessionsPage — Crawl Sessions list for the active website.
//
// Layout ported from .design-ref/project/pages.jsx (PageHeader + .card +
// .sessions-table). PageHeader markup is inlined because no PageHeader
// component exists yet in src/components.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import SessionsTable from '../components/tables/SessionsTable';

export default function SessionsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (sessionsQuery.data)
      return `${sessionsQuery.data.length} ${
        sessionsQuery.data.length === 1 ? 'session' : 'sessions'
      } for the active site`;
    return '';
  })();

  return (
    <div className="page-grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Crawl sessions</h1>
          <div className="page-subtitle">{subtitle}</div>
        </div>
      </div>

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to see sessions.
          </p>
        </div>
      )}

      {activeSiteId && sessionsQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">Loading sessions…</p>
        </div>
      )}

      {activeSiteId && sessionsQuery.isError && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p style={{ color: 'var(--error, #f87171)' }}>
            Failed to load sessions
            {sessionsQuery.error instanceof Error
              ? `: ${sessionsQuery.error.message}`
              : '.'}
          </p>
        </div>
      )}

      {activeSiteId && sessionsQuery.data && (
        <SessionsTable
          sessions={sessionsQuery.data}
          activeSiteId={activeSiteId}
        />
      )}
    </div>
  );
}
