// Topbar.tsx — top action bar of the Lattice shell.
//
// Stream E (Day 1): the URL field reflects the active site (read-only
// once one is selected), an "Add site" button reveals an inline registration
// form, and "Start crawl" is wired to POST /websites/<id>/crawl/. On success
// we navigate to /sessions where the new pending row will show up.
//
// Pause/Stop remain disabled — Stop will be wired by Stream F at the row
// level via the cancel endpoint.
//
// Day 5: the "AI Insights" button opens AIInsightsDrawer for the most
// recent session of the active site. The drawer itself handles the
// available=false placeholder, so we don't probe the backend up front — we
// just hide the button when there's no active site or no recent session.
//
// Polish pass: when the latest session is `running`, render the topbar
// progress sub-row from `.design-ref/project/shell.jsx:137`. The pill,
// counts, percent, elapsed/ETA timers, and bar all derive from real
// session + activity data.

import { useEffect, useState } from 'react';
import { useLocation } from 'wouter';
import Icon from './icons/Icon';
import AddSiteModal from './AddSiteModal';
import AIInsightsDrawer from './AIInsightsDrawer';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useWebsites } from '../api/hooks/useWebsites';
import { useSessions } from '../api/hooks/useSessions';
import { useStartCrawl } from '../api/hooks/useStartCrawl';
import { useActivity } from '../api/hooks/useActivity';
import type { CrawlSessionListItem } from '../api/types';

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
  const [showAddSite, setShowAddSite] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [, setLocation] = useLocation();
  const { activeSiteId } = useActiveSite();
  const websites = useWebsites();
  const sessions = useSessions(activeSiteId);
  const startCrawl = useStartCrawl();

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
  const displayDomain = activeSite?.domain ?? '';
  const hasNoSites =
    !websites.isLoading && (websites.data?.results?.length ?? 0) === 0;

  function handleStartCrawl() {
    if (!activeSiteId) return;
    startCrawl.mutate(activeSiteId, {
      onSuccess: () => setLocation('/sessions'),
    });
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
              placeholder={
                hasNoSites
                  ? 'Register your first site to start crawling'
                  : 'Select a site from the sidebar'
              }
              aria-label="Active site"
            />
            <span className="url-field-hint">
              {activeSite ? 'active' : 'none'}
            </span>
          </div>
          <button
            className="btn ghost"
            onClick={() => setShowAddSite((v) => !v)}
            aria-expanded={showAddSite}
            aria-controls="topbar-add-site-form"
          >
            <Icon name="plus" size={11} />
            <span>Add site</span>
          </button>
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
          {/* AI Insights (Day 5) — hidden until there's a session to analyse. */}
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
          <div className="topbar-divider" />
          <button className="icon-btn" aria-label="Search" disabled>
            <Icon name="search" size={15} />
          </button>
          <button className="icon-btn" aria-label="Refresh" disabled>
            <Icon name="refresh" size={15} />
          </button>
          <button
            className="icon-btn icon-btn-badge"
            aria-label="Notifications"
            disabled
          >
            <Icon name="bell" size={15} />
          </button>
          <div className="topbar-divider" />
          <button className="icon-btn" aria-label="Settings" disabled>
            <Icon name="settings" size={15} />
          </button>
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

      {showAddSite && (
        <div
          id="topbar-add-site-form"
          style={{ padding: '8px 16px 12px', maxWidth: 480 }}
        >
          <AddSiteModal onClose={() => setShowAddSite(false)} />
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
