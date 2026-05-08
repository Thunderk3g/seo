// SessionsPage — Crawl Sessions list for the active website.
//
// Layout ported from .design-ref/project/pages.jsx (PageHeader + .card +
// .sessions-table). Uses the shared `<PageHeader />` component now and
// surfaces a primary "New crawl" CTA wired to useStartCrawl().

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useStartCrawl } from '../api/hooks/useStartCrawl';
import PageHeader from '../components/PageHeader';
import SessionsTable from '../components/tables/SessionsTable';

export default function SessionsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  const startCrawl = useStartCrawl();

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (sessionsQuery.data)
      return `${sessionsQuery.data.length} ${
        sessionsQuery.data.length === 1 ? 'session' : 'sessions'
      } for the active site`;
    return '';
  })();

  const startError =
    startCrawl.error instanceof Error ? startCrawl.error.message : null;

  return (
    <div className="page-grid">
      <PageHeader
        title="Crawl sessions"
        subtitle={subtitle}
        actions={
          <button
            type="button"
            className="btn primary"
            disabled={!activeSiteId || startCrawl.isPending}
            onClick={() => activeSiteId && startCrawl.mutate(activeSiteId)}
            title={
              activeSiteId ? 'Start a fresh crawl on the active site' : 'No active site'
            }
          >
            <span>{startCrawl.isPending ? 'Starting…' : 'New crawl'}</span>
          </button>
        }
      />

      {startError && (
        <div
          className="card"
          style={{ padding: 'var(--pad)', color: 'var(--error, #f87171)' }}
        >
          Failed to start crawl: {startError}
        </div>
      )}

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
