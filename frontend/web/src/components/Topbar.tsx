// Topbar.tsx — Bajaj SEO property header.
//
// Reshaped from the legacy crawler topbar into a property-selector +
// CTA strip. Left side carries the active domain pill (Bajaj only for
// now — the system has one property) and the legacy URL-aware crawler
// shortcuts. Right side surfaces "Run new grade" and AI Insights when
// a session is available.
//
// The progress sub-row is preserved for crawler runs so the existing
// /crawler pages still show their inline status.

import { useEffect, useState } from 'react';
import { useLocation } from 'wouter';
import Icon from './icons/Icon';
import AIInsightsDrawer from './AIInsightsDrawer';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useWebsites } from '../api/hooks/useWebsites';
import { useSessions } from '../api/hooks/useSessions';
import { useStartCrawl } from '../api/hooks/useStartCrawl';
import { useActivity } from '../api/hooks/useActivity';
import { useStartGrade } from '../api/hooks/useGrade';
import type { CrawlSessionListItem } from '../api/types';

const PRIMARY_DOMAIN = 'bajajlifeinsurance.com';

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function formatClock(totalSec: number): string {
  if (!Number.isFinite(totalSec) || totalSec < 0) totalSec = 0;
  // Cap so the display never widens unexpectedly (99:59 hard ceiling
  // matches the audit guidance).
  const capped = Math.min(totalSec, 99 * 60 + 59);
  const m = Math.floor(capped / 60);
  const s = Math.floor(capped % 60);
  return `${pad(m)}:${pad(s)}`;
}

function computeEta(session: CrawlSessionListItem): string {
  const remaining = Math.max(
    0,
    session.total_urls_discovered - session.total_urls_crawled,
  );
  if (remaining === 0) return '00:00';
  // Rough estimate per the audit: remaining * avg_response_time_ms /
  // concurrency. We don't have the live crawl_config concurrency exposed
  // on the session list payload, so fall back to 1 (worst-case ETA, still
  // useful as an upper bound).
  const avgMs = session.avg_response_time_ms || 0;
  if (avgMs <= 0) return '—';
  const concurrency = 1;
  const etaSec = Math.round((remaining * avgMs) / concurrency / 1000);
  return formatClock(etaSec);
}

export default function Topbar() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [, setLocation] = useLocation();
  const { activeSiteId } = useActiveSite();
  const websites = useWebsites();
  const sessions = useSessions(activeSiteId);
  const startCrawl = useStartCrawl();
  const startGrade = useStartGrade();

  // Most recent session of the active site — drives the drawer's sessionId
  // and the progress sub-row. Sessions are returned ordered by -started_at,
  // so the head is the latest.
  const latestSession = sessions.data?.[0] ?? null;
  const latestSessionId = latestSession?.id ?? null;
  const showInsightsButton = Boolean(activeSiteId && latestSessionId);

  const runningSession =
    latestSession && latestSession.status === 'running' ? latestSession : null;

  // Live activity gives us the "current URL" being crawled. Polling is
  // gated on session status inside the hook, so this is free when idle.
  const activity = useActivity({
    sessionId: runningSession ? latestSessionId : null,
    status: runningSession?.status ?? null,
    limit: 5,
  });
  const currentUrl = activity.data?.[0]?.url ?? '—';

  // Live elapsed: ticked locally so the timer keeps moving between the
  // 2 s overview poll cycles. Only mounted while the session is running.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!runningSession) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [runningSession]);

  const activeSite = websites.data?.results?.find((w) => w.id === activeSiteId) ?? null;
  // Legacy crawler URL field stays for the crawler pages; the new SEO
  // surface always operates against the single configured Bajaj domain.
  const displayDomain = activeSite?.domain ?? PRIMARY_DOMAIN;

  function handleStartCrawl() {
    if (!activeSiteId) return;
    startCrawl.mutate(activeSiteId, {
      onSuccess: () => setLocation('/sessions'),
    });
  }

  function handleStartGrade() {
    startGrade.mutate(
      { domain: PRIMARY_DOMAIN, sync: false },
      {
        onSuccess: (resp) => setLocation(`/grade/${resp.id}`),
      },
    );
  }

  const startDisabled =
    !activeSiteId ||
    startCrawl.isPending ||
    websites.isLoading ||
    Boolean(runningSession);

  // Derived progress numbers — only used when runningSession is set.
  let crawled = 0;
  let total = 0;
  let pct = 0;
  let elapsed = '—';
  let eta = '—';
  if (runningSession) {
    crawled = runningSession.total_urls_crawled;
    total = runningSession.total_urls_discovered;
    pct = Math.round((crawled / Math.max(total, 1)) * 100);
    if (runningSession.started_at) {
      const startMs = new Date(runningSession.started_at).getTime();
      if (Number.isFinite(startMs)) {
        elapsed = formatClock((now - startMs) / 1000);
      }
    }
    eta = computeEta(runningSession);
  }

  return (
    <header className="topbar">
      <div className="topbar-row">
        <div className="topbar-controls">
          <div className="url-field">
            <Icon name="globe" size={14} />
            <input
              type="text"
              value={displayDomain}
              readOnly
              placeholder="Select a site from the sidebar"
              aria-label="Active site"
            />
            <span className="url-field-hint">
              {activeSite ? 'active' : 'bajaj'}
            </span>
          </div>
          <button
            className={'btn primary ' + (startDisabled ? 'btn-disabled' : '')}
            disabled={startDisabled}
            onClick={handleStartCrawl}
            title={
              activeSiteId
                ? 'Trigger a crawl for the active site'
                : 'Register a site first'
            }
          >
            <Icon name="play" size={11} />
            <span>
              {runningSession
                ? 'Crawling…'
                : startCrawl.isPending
                ? 'Starting…'
                : 'Start crawl'}
            </span>
          </button>
          <button className="btn ghost" disabled>
            <Icon name="pause" size={11} />
            <span>Pause</span>
          </button>
          <button className="btn ghost" disabled>
            <Icon name="stop" size={11} />
            <span>Stop</span>
          </button>
        </div>

        <div className="topbar-actions">
          <button
            className="btn primary"
            onClick={handleStartGrade}
            disabled={startGrade.isPending}
            title="Run a new SEO grading run"
          >
            <Icon name="zap" size={13} />
            <span>{startGrade.isPending ? 'Starting…' : 'Run grade'}</span>
          </button>
          {showInsightsButton && (
            <button
              className="btn ghost"
              onClick={() => setDrawerOpen(true)}
              title="Open AI insights for the latest crawl"
            >
              <Icon name="zap" size={15} />
              <span>Insights</span>
            </button>
          )}
        </div>
      </div>

      {runningSession && (
        <div className="topbar-progress">
          <div className="progress-meta">
            <span className="crawl-state-pill running">
              <span className="state-dot" />
              Crawling
            </span>
            <span className="progress-current">{currentUrl}</span>
          </div>
          <div className="progress-stats">
            <span>
              <b>{crawled.toLocaleString()}</b> / {total.toLocaleString()}
            </span>
            <span className="text-muted">·</span>
            <span>
              <b>{pct}%</b>
            </span>
            <span className="text-muted">·</span>
            <span>
              elapsed{' '}
              <b style={{ fontVariantNumeric: 'tabular-nums' }}>{elapsed}</b>
            </span>
            <span className="text-muted">·</span>
            <span>
              ETA <b style={{ fontVariantNumeric: 'tabular-nums' }}>{eta}</b>
            </span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {startCrawl.isError && (
        <div
          role="alert"
          style={{
            padding: '6px 16px',
            color: 'var(--error, #f87171)',
            fontSize: 12,
          }}
        >
          {startCrawl.error instanceof Error
            ? startCrawl.error.message
            : 'Failed to start crawl.'}
        </div>
      )}

      <AIInsightsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        sessionId={latestSessionId}
      />
    </header>
  );
}
