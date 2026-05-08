// Sidebar.tsx — left rail of the Lattice shell.
//
// Stream E (Day 1) added the project picker section that the Day-0 port
// intentionally omitted. Lists registered sites from useWebsites, marks
// the active one (mint accent), switches `activeSiteId` on click, and
// exposes an "+ Add site" button that opens the same AddSiteModal the
// topbar uses (each instance owns its own visibility — no lifted state,
// no shared event bus, see advisor note).
//
// Polish pass: the project menu is now a real dropdown (toggled by the
// `proj-select` button, closed on outside-mousedown), the Issues nav item
// gets a live badge fed by useIssues(latestSessionId), and a QuickStats
// inset surfaces the most recent session's KPIs under the project picker.

import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'wouter';
import Icon from './icons/Icon';
import BrandMark from './icons/BrandMark';
import AddSiteModal from './AddSiteModal';
import QuickStats from './QuickStats';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useWebsites } from '../api/hooks/useWebsites';
import { useSessions } from '../api/hooks/useSessions';
import { useIssues } from '../api/hooks/useIssues';

interface NavItem {
  id: string;
  label: string;
  icon: string;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', path: '/' },
  { id: 'sessions', label: 'Crawl Sessions', icon: 'sessions', path: '/sessions' },
  { id: 'pages', label: 'Pages / URLs', icon: 'pages', path: '/pages' },
  { id: 'issues', label: 'Issues', icon: 'issues', path: '/issues' },
  { id: 'analytics', label: 'Analytics', icon: 'analytics', path: '/analytics' },
  {
    id: 'visualizations',
    label: 'Visualizations',
    icon: 'visualizations',
    path: '/visualizations',
  },
  { id: 'exports', label: 'Exports', icon: 'exports', path: '/exports' },
  { id: 'settings', label: 'Settings', icon: 'settings', path: '/settings' },
];

function isActive(path: string, current: string): boolean {
  if (path === '/') return current === '/';
  return current === path || current.startsWith(path + '/');
}

export default function Sidebar() {
  const [location] = useLocation();
  const [showAddSite, setShowAddSite] = useState(false);
  const [projOpen, setProjOpen] = useState(false);
  const projPickerRef = useRef<HTMLDivElement | null>(null);
  const { activeSiteId, setActiveSite } = useActiveSite();
  const websites = useWebsites();
  const sites = websites.data?.results ?? [];
  const activeSite = sites.find((s) => s.id === activeSiteId) ?? null;

  // Latest session of the active site — drives the Issues nav badge and
  // the QuickStats inset. Sessions come back ordered by -started_at, so the
  // head is the latest.
  const sessions = useSessions(activeSiteId);
  const latestSessionId = sessions.data?.[0]?.id ?? null;
  const issues = useIssues(latestSessionId);
  const errorIssueCount = (issues.data ?? []).reduce(
    (sum, i) => sum + (i.severity === 'error' ? i.count : 0),
    0,
  );

  // Close the project dropdown on outside mousedown. Only attach the
  // listener while the menu is open so we're not paying for it otherwise.
  useEffect(() => {
    if (!projOpen) return;
    function handleMouseDown(e: MouseEvent) {
      const root = projPickerRef.current;
      if (root && !root.contains(e.target as Node)) {
        setProjOpen(false);
      }
    }
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [projOpen]);

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">
          <BrandMark size={20} color="var(--accent)" />
        </div>
        <div>
          <div className="brand-name">Lattice</div>
          <div className="brand-sub">SEO Crawler</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((it) => (
          <Link
            key={it.id}
            href={it.path}
            className={'nav-item ' + (isActive(it.path, location) ? 'active' : '')}
          >
            <Icon name={it.icon} size={16} />
            <span>{it.label}</span>
            {it.id === 'issues' && errorIssueCount > 0 && (
              <span className="nav-badge">{errorIssueCount}</span>
            )}
          </Link>
        ))}
      </nav>

      {/* Project picker — TS port of .design-ref/project/shell.jsx Sidebar. */}
      <div className="sidebar-section" ref={projPickerRef}>
        <div className="sidebar-section-title">Project</div>

        {websites.isLoading && (
          <div
            style={{
              padding: '0 8px',
              fontSize: 11.5,
              color: 'var(--text-3)',
            }}
          >
            Loading sites…
          </div>
        )}

        {!websites.isLoading && sites.length === 0 && (
          <div className="proj-menu">
            <div
              style={{
                padding: '6px 8px',
                fontSize: 11.5,
                color: 'var(--text-3)',
              }}
            >
              No sites yet
            </div>
            <button
              className="proj-menu-item"
              onClick={() => setShowAddSite(true)}
            >
              <Icon name="plus" size={12} />
              <span>Add site</span>
            </button>
          </div>
        )}

        {!websites.isLoading && sites.length > 0 && (
          <>
            <button
              className="proj-select"
              type="button"
              onClick={() => setProjOpen((v) => !v)}
              aria-expanded={projOpen}
              aria-haspopup="menu"
            >
              <div className="proj-info">
                <div className="proj-name">
                  {activeSite ? activeSite.name || activeSite.domain : 'No site selected'}
                </div>
                <div className="proj-sub">
                  {sites.length} site{sites.length === 1 ? '' : 's'} registered
                </div>
              </div>
              <Icon name="chevDown" size={14} />
            </button>
            {projOpen && (
              <div className="proj-menu" role="menu">
                {sites.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    role="menuitem"
                    className={
                      'proj-menu-item ' + (s.id === activeSiteId ? 'active' : '')
                    }
                    onClick={() => {
                      setActiveSite(s.id);
                      setProjOpen(false);
                    }}
                  >
                    <span>{s.name || s.domain}</span>
                    <span className="proj-menu-count">{s.domain}</span>
                  </button>
                ))}
                <div className="proj-menu-sep" />
                <button
                  type="button"
                  role="menuitem"
                  className="proj-menu-item"
                  onClick={() => {
                    setProjOpen(false);
                    setShowAddSite(true);
                  }}
                >
                  <Icon name="plus" size={12} />
                  <span>Add site</span>
                </button>
              </div>
            )}
          </>
        )}

        {showAddSite && (
          <AddSiteModal onClose={() => setShowAddSite(false)} />
        )}
      </div>

      {/* Quick stats — only renders when there's a session to summarise. */}
      <QuickStats sessionId={latestSessionId} />

      <div style={{ flex: 1 }} />

      <div className="sidebar-user">
        <div className="user-avatar">AV</div>
        <div className="user-info">
          <div className="user-name">Aman Verma</div>
          <div className="user-role">Administrator</div>
        </div>
        <button className="icon-btn" aria-label="Account menu">
          <Icon name="more" size={14} />
        </button>
      </div>
    </aside>
  );
}
