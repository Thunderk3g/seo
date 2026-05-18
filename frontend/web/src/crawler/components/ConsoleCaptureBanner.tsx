import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { crawlerApi } from '../api';

/**
 * Compact banner + button that kicks off a real-browser console capture
 * via Playwright. Polls the status endpoint while a capture is running so
 * the operator sees live progress (X/Y processed, latest URL).
 *
 * Lives just under the GscCoverageUploader on /crawler/reports.
 */
export default function ConsoleCaptureBanner() {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    processed: number;
    total: number;
    rows: number;
    last_url: string;
  } | null>(null);
  const pollRef = useRef<number | null>(null);

  // Poll the status endpoint while a capture is alive.
  useEffect(() => {
    if (!busy) return;
    let alive = true;
    async function tick() {
      try {
        const s = await crawlerApi.consoleCaptureStatus();
        if (!alive) return;
        setProgress({
          processed: s.processed,
          total: s.total,
          rows: s.console_rows_written,
          last_url: s.last_url,
        });
        if (!s.is_running) {
          setBusy(false);
          if (s.total > 0) {
            setStatus(
              `Done — inspected ${s.processed}/${s.total} URL(s); wrote ${s.console_rows_written} console event(s).`
            );
            // Reload so the Errors-by-type "Console log entries" card refreshes.
            window.setTimeout(() => window.location.reload(), 1200);
          }
        }
      } catch (e) {
        // Keep polling; status endpoint is cheap and a transient error
        // is no reason to abandon the in-flight capture.
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    }
    pollRef.current = window.setInterval(tick, 2000) as unknown as number;
    tick();
    return () => {
      alive = false;
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, [busy]);

  async function start() {
    setError(null);
    setStatus(null);
    setProgress(null);
    setBusy(true);
    try {
      const res = await crawlerApi.startConsoleCapture({
        limit: 200,
        subdomain: 'www',
        status: '200',
        levels: 'error,warning',
      });
      if (!res.ok) {
        setError(res.message || 'Could not start capture.');
        setBusy(false);
        return;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  async function stop() {
    try {
      await crawlerApi.stopConsoleCapture();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const pct = progress && progress.total
    ? Math.round((progress.processed / progress.total) * 100)
    : 0;

  return (
    <div className="cc-gsc-banner card">
      <div className="cc-gsc-banner__icon">
        <Icon name="terminal" />
      </div>
      <div className="cc-gsc-banner__body">
        <div className="cc-gsc-banner__title">Browser console capture</div>
        <div className="cc-gsc-banner__desc">
          Runs headless Chromium against the top 200 www pages (HTTP 200, filtered to
          {' '}<code>error</code> + <code>warning</code> levels) and writes real JS errors,
          uncaught exceptions, and failed network requests into{' '}
          <code>crawl_console_log.csv</code>. Takes ~3 sec per URL.
        </div>
        {busy && progress && (
          <div className="cc-gsc-banner__status cc-gsc-banner__status--ok"
               style={{ fontVariantNumeric: 'tabular-nums' }}>
            Inspecting <b>{progress.processed}</b> / {progress.total} ({pct}%)
            · {progress.rows} console event(s) so far
            {progress.last_url ? <><br /><small style={{ opacity: 0.7 }}>{progress.last_url}</small></> : null}
          </div>
        )}
        {!busy && status && (
          <div className="cc-gsc-banner__status cc-gsc-banner__status--ok">{status}</div>
        )}
        {error && (
          <div className="cc-gsc-banner__status cc-gsc-banner__status--err">{error}</div>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'stretch' }}>
        {!busy ? (
          <button type="button" className="btn btn-primary" onClick={start}>
            <Icon name="play_arrow" />
            Capture console
          </button>
        ) : (
          <button type="button" className="btn btn-ghost" onClick={stop}>
            <Icon name="stop" />
            Stop capture
          </button>
        )}
      </div>
    </div>
  );
}
