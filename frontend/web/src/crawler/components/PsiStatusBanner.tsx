// Banner that surfaces PSI / Core Web Vitals state on the Reports
// landing page. Three modes:
//
//   1. LIVE — a crawl is running and the inline PSI scheduler is
//      processing URLs. Shows a progress bar (completed / submitted)
//      and updates every 5 s.
//   2. SUCCESS — the most recent crawl finished and merged PSI rows
//      into crawl_results.csv. Green confirmation card.
//   3. FAILURE — PSI was skipped (no SA file, PSI_ENABLED=false,
//      adapter error). Red card with the exact reason and remediation
//      hints.
//
// When no crawl has ever run, the banner renders nothing (clean slate
// for first-time installs).

import { useEffect, useState } from 'react';
import Icon from './Icon';
import { crawlerApi } from '../api';

type PsiStatus = Awaited<ReturnType<typeof crawlerApi.psiStatus>>;
type PsiProgress = Awaited<ReturnType<typeof crawlerApi.psiProgress>>;

function formatTime(iso?: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function isProgressActive(p: PsiProgress | null): boolean {
  if (!p || Object.keys(p).length === 0) return false;
  if (p.disabled) return false;
  // is_running flips false the moment the scheduler.stop() drains;
  // but as long as we have a started_at, the run still exists in
  // memory and we want to render its final-state snapshot for a few
  // seconds rather than blanking the banner mid-merge.
  return Boolean(p.is_running || p.started_at);
}

export default function PsiStatusBanner() {
  const [status, setStatus] = useState<PsiStatus | null>(null);
  const [progress, setProgress] = useState<PsiProgress | null>(null);

  // One-shot fetch of last-run status; refreshed by the polling effect
  // below whenever a live run wraps up.
  const refreshStatus = () => {
    crawlerApi
      .psiStatus()
      .then((s) => setStatus(s))
      .catch(() => setStatus(null));
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  // Poll /psi/progress while a crawl is in flight. The first non-empty
  // response flips the banner into LIVE mode; when the scheduler ends,
  // we refresh /psi/status once to surface the merged-rows count.
  useEffect(() => {
    let alive = true;
    let wasRunning = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const p = await crawlerApi.psiProgress();
        if (!alive) return;
        setProgress(p);
        const running = Boolean(p.is_running);
        if (wasRunning && !running) {
          // Just finished — pull the persisted summary.
          refreshStatus();
        }
        wasRunning = running;
      } catch {
        if (alive) setProgress(null);
      } finally {
        if (alive) {
          timer = window.setTimeout(tick, 5000);
        }
      }
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  // ── LIVE: inline PSI scheduler is working ──────────────────────
  if (isProgressActive(progress) && progress) {
    const completed = progress.completed ?? 0;
    const submitted = progress.submitted ?? 0;
    const inFlight = progress.in_flight ?? 0;
    const failed = progress.failed ?? 0;
    const workers = progress.workers ?? 0;
    const pct = submitted > 0 ? Math.min(100, (completed / submitted) * 100) : 0;
    const live = Boolean(progress.is_running);
    return (
      <div
        className="card"
        style={{
          padding: 12,
          marginBottom: 16,
          borderColor: 'var(--accent)',
          background: 'rgba(59, 130, 246, 0.06)',
          color: 'var(--text-1)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon name="speed" />
          <strong>
            Page Speed (PSI) — {live ? 'running live' : 'final merge in progress'}
          </strong>
          {live && (
            <span
              style={{
                marginLeft: 'auto',
                fontSize: 12,
                color: 'var(--text-3)',
              }}
            >
              {workers} worker{workers === 1 ? '' : 's'} ·{' '}
              {(progress.strategies || []).join(', ')}
            </span>
          )}
        </div>
        <div
          style={{
            position: 'relative',
            height: 8,
            background: 'rgba(0,0,0,0.08)',
            borderRadius: 4,
            marginTop: 10,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: `${pct}%`,
              background: 'var(--accent)',
              transition: 'width 0.4s ease-out',
            }}
          />
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 6 }}>
          <strong>{completed.toLocaleString()}</strong> of{' '}
          <strong>{submitted.toLocaleString()}</strong> URLs scored
          {inFlight > 0 && (
            <>
              {' '}
              · <strong>{inFlight}</strong> in flight
            </>
          )}
          {failed > 0 && (
            <>
              {' '}
              · <strong>{failed}</strong> failed
            </>
          )}
        </div>
        {progress.last_url && (
          <div
            style={{
              fontSize: 12,
              color: 'var(--text-3)',
              marginTop: 4,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={progress.last_url}
          >
            Latest: <code>{progress.last_url}</code>
          </div>
        )}
      </div>
    );
  }

  if (!status || Object.keys(status).length === 0) {
    // No PSI run has happened yet — don't render anything.
    return null;
  }

  // ── SUCCESS ────────────────────────────────────────────────────
  if (status.ok) {
    const merged = status.rows_written ?? 0;
    const inspected = status.urls_inspected ?? 0;
    const failed = status.failed ?? 0;
    return (
      <div
        className="card"
        style={{
          padding: 12,
          marginBottom: 16,
          borderColor: 'var(--green)',
          background: 'rgba(34, 197, 94, 0.06)',
          color: 'var(--text-1)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon name="speed" />
          <strong>Page Speed (PSI) — last run OK</strong>
          {status.mode && (
            <span
              style={{
                marginLeft: 'auto',
                fontSize: 12,
                color: 'var(--text-3)',
              }}
            >
              mode: {status.mode}
            </span>
          )}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4 }}>
          Merged <strong>{merged}</strong> PSI rows into{' '}
          <code>crawl_results.csv</code> from{' '}
          <strong>{inspected}</strong> URLs
          {failed > 0 && (
            <>
              {' '}
              (<strong>{failed}</strong> URL{failed === 1 ? '' : 's'} failed)
            </>
          )}
          {status.finished_at && (
            <span style={{ marginLeft: 8, color: 'var(--text-3)' }}>
              · {formatTime(status.finished_at)}
            </span>
          )}
        </div>
      </div>
    );
  }

  // ── FAILURE ────────────────────────────────────────────────────
  return (
    <div
      className="card"
      style={{
        padding: 12,
        marginBottom: 16,
        borderColor: 'var(--red)',
        background: 'rgba(239, 68, 68, 0.06)',
        color: 'var(--text-1)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Icon name="warning" />
        <strong>Page Speed (PSI) capture skipped on the last run</strong>
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4 }}>
        <em>{status.error || 'Reason not recorded'}</em>
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 6 }}>
        The <code>pagespeed_score</code>, <code>lcp_ms</code>,{' '}
        <code>cls</code>, and <code>inp_ms</code> columns in the results
        table will stay empty until this is resolved. Common causes:{' '}
        PSI service-account file missing, PSI_ENABLED=false, or the
        crawler ran on an old Celery worker image.
        {status.finished_at && (
          <span style={{ marginLeft: 8 }}>
            · {formatTime(status.finished_at)}
          </span>
        )}
      </div>
    </div>
  );
}
