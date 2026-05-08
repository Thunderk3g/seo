// ExportsPage — generate + list export artifacts for the active site's
// latest crawl session.
//
// Layout (per spec §5.4.6):
//   TOP    .card  — six "Generate export" buttons in a grid.
//   BOTTOM .card  — "Recent exports" table (Filename, Kind, Rows, Size,
//                   Generated, Download).
//
// Page state machine mirrors IssuesPage: useActiveSite → useSessions →
// pick sessions[0] → useExports(sessionId).
//
// Download trigger is a plain <a href download> rather than a fetch+blob:
//   - Vite dev proxies /api/* to the Django backend, so a relative URL
//     works in dev and prod alike.
//   - The backend already sets Content-Disposition: attachment, so the
//     browser opens its native save dialog directly.
//   - No JS allocation for large files; no need to revoke object URLs.

import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useExports, useCreateExport } from '../api/hooks/useExports';
import type { ExportKind, ExportRecordSummary } from '../api/types';

interface ExportKindMeta {
  kind: ExportKind;
  label: string;
}

// Display labels mirror the backend KIND_CHOICES tuple in
// backend/apps/crawl_sessions/models.py around line 449.
const EXPORT_KINDS: ExportKindMeta[] = [
  { kind: 'urls.csv', label: 'URLs (CSV)' },
  { kind: 'issues.xlsx', label: 'Issues (XLSX)' },
  { kind: 'sitemap.xml', label: 'Sitemap (XML)' },
  { kind: 'broken-links.csv', label: 'Broken Links (CSV)' },
  { kind: 'redirects.csv', label: 'Redirects (CSV)' },
  { kind: 'metadata.json', label: 'Metadata (JSON)' },
];

const KIND_LABEL: Record<ExportKind, string> = EXPORT_KINDS.reduce(
  (acc, k) => {
    acc[k.kind] = k.label;
    return acc;
  },
  {} as Record<ExportKind, string>,
);

// 7-column grid: Filename | Kind | Rows | Size | Generated | Download.
// Matches the .bt-row / big-url-table styles already used by PagesTable.
const RECENT_GRID = '36px 2fr 1.4fr 90px 100px 170px 110px';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatGeneratedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function downloadHref(sessionId: string, exportId: string): string {
  // Relative path — Vite dev proxies /api/* to the Django backend, so
  // this works without an env var in dev and prod alike.
  return `/api/v1/sessions/${sessionId}/exports/${exportId}/download/`;
}

export default function ExportsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Use the most recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;
  const sessionId = session?.id ?? null;

  const exportsQuery = useExports(sessionId);
  const createMutation = useCreateExport();

  const records: ExportRecordSummary[] = exportsQuery.data ?? [];

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (!session) return 'No crawl sessions yet — start one from the topbar';
    if (exportsQuery.isPending) return 'Loading exports…';
    const n = records.length;
    return `${n.toLocaleString()} export${n === 1 ? '' : 's'} on file`;
  })();

  // Track which kind is currently being generated so we can disable just
  // that button (TanStack mutation only tracks the latest call's variables).
  const pendingKind: ExportKind | null =
    createMutation.isPending && createMutation.variables
      ? createMutation.variables.kind
      : null;

  const createError =
    createMutation.error instanceof Error ? createMutation.error.message : null;

  function handleGenerate(kind: ExportKind) {
    if (!sessionId) return;
    createMutation.mutate({ sessionId, kind });
  }

  return (
    <div className="page-grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Exports</h1>
          <div className="page-subtitle">{subtitle}</div>
        </div>
      </div>

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to generate exports.
          </p>
        </div>
      )}

      {activeSiteId && !session && !sessionsQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No crawl sessions exist for this site yet. Start one from the
            topbar to generate exports.
          </p>
        </div>
      )}

      {session && (
        <>
          {/* TOP — generate-export panel */}
          <div className="card">
            <div className="card-head">
              <h3>Generate export</h3>
            </div>
            <div
              style={{
                padding: 'var(--pad)',
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 12,
              }}
            >
              {EXPORT_KINDS.map((meta) => {
                const busy = pendingKind === meta.kind;
                return (
                  <div
                    key={meta.kind}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                    }}
                  >
                    <button
                      type="button"
                      className="btn"
                      disabled={busy || createMutation.isPending}
                      onClick={() => handleGenerate(meta.kind)}
                      title={`Generate ${meta.label}`}
                      style={{ width: '100%', justifyContent: 'center' }}
                    >
                      <span>{busy ? 'Generating…' : meta.label}</span>
                    </button>
                  </div>
                );
              })}
            </div>
            {createError && (
              <div
                style={{
                  padding: '0 var(--pad) var(--pad)',
                  color: 'var(--error, #f87171)',
                  fontSize: 12,
                }}
              >
                Failed to generate export: {createError}
              </div>
            )}
          </div>

          {/* BOTTOM — recent exports table */}
          <div className="card">
            <div className="card-head">
              <h3>Recent exports</h3>
            </div>

            {exportsQuery.isError && (
              <div style={{ padding: 'var(--pad)' }}>
                <p style={{ color: 'var(--error, #f87171)' }}>
                  Failed to load exports
                  {exportsQuery.error instanceof Error
                    ? `: ${exportsQuery.error.message}`
                    : '.'}
                </p>
              </div>
            )}

            {exportsQuery.isPending && (
              <div style={{ padding: 'var(--pad)' }}>
                <p className="text-muted">Loading exports…</p>
              </div>
            )}

            {exportsQuery.data && records.length === 0 && (
              <div style={{ padding: 'var(--pad)' }}>
                <p className="text-muted">
                  No exports yet — generate one above.
                </p>
              </div>
            )}

            {exportsQuery.data && records.length > 0 && (
              <div className="big-url-table">
                <div
                  className="bt-row bt-head"
                  style={{ gridTemplateColumns: RECENT_GRID }}
                >
                  <div className="bt-num">#</div>
                  <div>Filename</div>
                  <div>Kind</div>
                  <div style={{ textAlign: 'right' }}>Rows</div>
                  <div style={{ textAlign: 'right' }}>Size</div>
                  <div>Generated</div>
                  <div>Download</div>
                </div>

                {records.map((r, i) => (
                  <div
                    key={r.id}
                    className="bt-row"
                    style={{ gridTemplateColumns: RECENT_GRID }}
                  >
                    <div className="bt-num">{i + 1}</div>
                    <div className="bt-url" title={r.filename}>
                      <span className="bt-url-link">{r.filename}</span>
                    </div>
                    <div className="text-muted-2">
                      {KIND_LABEL[r.kind] ?? r.kind}
                    </div>
                    <div className="bt-num2">
                      {r.row_count.toLocaleString()}
                    </div>
                    <div className="bt-num2">{formatBytes(r.size_bytes)}</div>
                    <div className="text-muted-2">
                      {formatGeneratedAt(r.generated_at)}
                    </div>
                    <div>
                      <a
                        className="btn ghost"
                        href={downloadHref(sessionId!, r.id)}
                        download={r.filename}
                        title={`Download ${r.filename}`}
                      >
                        <span>Download</span>
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
