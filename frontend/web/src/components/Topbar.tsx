// Topbar.tsx — top action bar of the Lattice shell.
//
// Stream E (Day 1): the URL field now reflects the active site (read-only
// once one is selected), an "Add site" button reveals an inline registration
// form, and "Start crawl" is wired to POST /websites/<id>/crawl/. On success
// we navigate to /sessions where the new pending row will show up.
//
// Pause/Stop remain disabled — Stop will be wired by Stream F at the row
// level via the cancel endpoint. AI Insights stays disabled until Day 5.

import { useState } from 'react';
import { useLocation } from 'wouter';
import Icon from './icons/Icon';
import AddSiteModal from './AddSiteModal';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useWebsites } from '../api/hooks/useWebsites';
import { useStartCrawl } from '../api/hooks/useStartCrawl';

export default function Topbar() {
  const [showAddSite, setShowAddSite] = useState(false);
  const [, setLocation] = useLocation();
  const { activeSiteId } = useActiveSite();
  const websites = useWebsites();
  const startCrawl = useStartCrawl();

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
    !activeSiteId || startCrawl.isPending || websites.isLoading;

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
            <span>{startCrawl.isPending ? 'Starting…' : 'Start crawl'}</span>
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
          {/* AI Insights — added per spec §5.4.9. Disabled until first crawl (Day 5). */}
          <button
            className="btn ghost"
            disabled
            title="Available after first crawl (Day 5)"
          >
            <Icon name="zap" size={13} />
            <span>AI Insights</span>
          </button>
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
    </header>
  );
}
