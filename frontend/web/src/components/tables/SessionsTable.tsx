// SessionsTable.tsx — Crawl Sessions list for the active website.
//
// Column order matches `.design-ref/project/pages.jsx:271–294`:
//   Session | Started | Type | Status | URLs | Errors | Warnings | Duration | actions
//
// Backend constraint: CrawlSessionListSerializer exposes only
// `total_urls_failed` and not a separate "warnings" count. Errors renders
// `total_urls_failed`; Warnings shows `—` with a tooltip explaining the
// serializer gap. URLs renders `crawled/discovered` so the operator can see
// crawl progress at a glance.
//
// Per-row action:
//   pending | running   → "Cancel" (POST /sessions/:id/cancel/)
//   completed | failed | cancelled → "Re-run" (via useStartCrawl)
// (The design ref shows only an icon-button "more" menu; we keep functional
// inline buttons because they actually work.)

import { useCancelSession } from '../../api/hooks/useCancelSession';
import { useStartCrawl } from '../../api/hooks/useStartCrawl';
import type {
  CrawlSessionListItem,
  SessionStatus,
} from '../../api/types';

interface SessionsTableProps {
  sessions: CrawlSessionListItem[];
  activeSiteId: string | null;
}

// 9 columns: Session | Started | Type | Status | URLs | Errors | Warnings | Duration | Actions
const GRID_COLUMNS =
  '110px 170px 110px 120px 120px 70px 80px 90px 110px';

const TYPE_LABEL: Record<CrawlSessionListItem['session_type'], string> = {
  scheduled: 'Scheduled',
  on_demand: 'On demand',
  url_inspection: 'URL inspection',
};

const STATUS_LABEL: Record<SessionStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

// Map all 5 SessionStatus values onto the 3 CSS variants that exist
// (sess-running / sess-completed / sess-failed). 'pending' borrows the
// running pulse to convey "queued"; 'cancelled' uses the muted completed
// look. Don't add CSS — lattice.css is read-only.
function statusClass(status: SessionStatus): string {
  if (status === 'running' || status === 'pending') return 'sess-running';
  if (status === 'failed') return 'sess-failed';
  return 'sess-completed'; // completed | cancelled
}

function isLive(status: SessionStatus): boolean {
  return status === 'pending' || status === 'running';
}

function formatStarted(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${String(s).padStart(2, '0')}s`;
}

interface SessionRowProps {
  session: CrawlSessionListItem;
  activeSiteId: string | null;
  onCancel: (sessionId: string) => void;
  cancelPendingId: string | null;
  cancelErrorBySessionId: Record<string, string>;
  onRerun: () => void;
  rerunPending: boolean;
  rerunError: string | null;
}

function SessionRow({
  session,
  activeSiteId,
  onCancel,
  cancelPendingId,
  cancelErrorBySessionId,
  onRerun,
  rerunPending,
  rerunError,
}: SessionRowProps) {
  const live = isLive(session.status);
  const cancelBusy = cancelPendingId === session.id;
  const cancelErr = cancelErrorBySessionId[session.id];

  return (
    <div className="sess-row" style={{ gridTemplateColumns: GRID_COLUMNS }}>
      <div className="sess-id" title={session.id}>
        {session.id.slice(0, 8)}
      </div>
      <div className="text-muted-2">{formatStarted(session.started_at)}</div>
      <div className="text-muted-2">{TYPE_LABEL[session.session_type]}</div>
      <div>
        <span className={`sess-status ${statusClass(session.status)}`}>
          <span className="state-dot" />
          {STATUS_LABEL[session.status]}
        </span>
      </div>
      <div className="num">
        {session.total_urls_crawled.toLocaleString()}
        <span className="text-muted">
          /{session.total_urls_discovered.toLocaleString()}
        </span>
      </div>
      <div className="num">
        <span
          style={{
            color: session.total_urls_failed > 0 ? '#f87171' : 'inherit',
          }}
        >
          {session.total_urls_failed.toLocaleString()}
        </span>
      </div>
      <div
        className="num text-muted"
        title="Backend serializer does not yet split errors/warnings"
      >
        —
      </div>
      <div
        className="text-muted-2"
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {formatDuration(session.duration_seconds)}
      </div>
      <div>
        {live ? (
          <button
            type="button"
            className="btn ghost"
            disabled={cancelBusy}
            onClick={() => onCancel(session.id)}
            title="Cancel this crawl"
          >
            <span>{cancelBusy ? 'Cancelling…' : 'Cancel'}</span>
          </button>
        ) : (
          <button
            type="button"
            className="btn ghost"
            disabled={!activeSiteId || rerunPending}
            onClick={onRerun}
            title={
              activeSiteId ? 'Re-run a crawl on this site' : 'No active site'
            }
          >
            <span>{rerunPending ? 'Starting…' : 'Re-run'}</span>
          </button>
        )}
        {cancelErr && live && (
          <div
            style={{
              fontSize: 10.5,
              color: 'var(--error, #f87171)',
              marginTop: 4,
            }}
          >
            {cancelErr}
          </div>
        )}
        {rerunError && !live && (
          <div
            style={{
              fontSize: 10.5,
              color: 'var(--error, #f87171)',
              marginTop: 4,
            }}
          >
            {rerunError}
          </div>
        )}
      </div>
    </div>
  );
}

export default function SessionsTable({
  sessions,
  activeSiteId,
}: SessionsTableProps) {
  const cancelMutation = useCancelSession(activeSiteId);
  const rerunMutation = useStartCrawl();

  // Track per-row cancel error keyed by sessionId so concurrent rows don't
  // cross-contaminate. Stored in mutation context via TanStack? Simpler:
  // derive from the single mutation's `variables` + `error` snapshot.
  const cancelErrorBySessionId: Record<string, string> = {};
  if (cancelMutation.error && cancelMutation.variables) {
    cancelErrorBySessionId[cancelMutation.variables] =
      cancelMutation.error instanceof Error
        ? cancelMutation.error.message
        : 'Cancel failed';
  }

  const cancelPendingId =
    cancelMutation.isPending && cancelMutation.variables
      ? cancelMutation.variables
      : null;

  const rerunError =
    rerunMutation.error instanceof Error ? rerunMutation.error.message : null;

  function handleRerun() {
    if (!activeSiteId) return;
    rerunMutation.mutate(activeSiteId);
  }

  if (sessions.length === 0) {
    return (
      <div className="card" style={{ padding: 'var(--pad)' }}>
        <p className="text-muted">
          No crawl sessions yet. Use the <strong>New crawl</strong> button
          above to launch the first one.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="sessions-table">
        <div
          className="sess-row sess-head"
          style={{ gridTemplateColumns: GRID_COLUMNS }}
        >
          <div>Session</div>
          <div>Started</div>
          <div>Type</div>
          <div>Status</div>
          <div className="num">URLs</div>
          <div className="num">Errors</div>
          <div className="num">Warnings</div>
          <div>Duration</div>
          <div>Actions</div>
        </div>
        {sessions.map((s) => (
          <SessionRow
            key={s.id}
            session={s}
            activeSiteId={activeSiteId}
            onCancel={(id) => cancelMutation.mutate(id)}
            cancelPendingId={cancelPendingId}
            cancelErrorBySessionId={cancelErrorBySessionId}
            onRerun={handleRerun}
            rerunPending={rerunMutation.isPending}
            rerunError={rerunError}
          />
        ))}
      </div>
    </div>
  );
}
