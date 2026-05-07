// Sidebar.tsx — left rail of the Lattice shell.
//
// Stream E (Day 1) adds the project picker section that the Day-0 port
// intentionally omitted. Lists registered sites from useWebsites, marks
// the active one (mint accent), switches `activeSiteId` on click, and
// exposes an "+ Add site" button that opens the same AddSiteModal the
// topbar uses (each instance owns its own visibility — no lifted state,
// no shared event bus, see advisor note).

import { useState } from 'react';
import { Link, useLocation } from 'wouter';
import Icon from './icons/Icon';
import BrandMark from './icons/BrandMark';
import AddSiteModal from './AddSiteModal';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useWebsites } from '../api/hooks/useWebsites';

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
  const { activeSiteId, setActiveSite } = useActiveSite();
  const websites = useWebsites();
  const sites = websites.data?.results ?? [];
  const activeSite = sites.find((s) => s.id === activeSiteId) ?? null;

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
          </Link>
        ))}
      </nav>

      {/* Project picker — TS port of .design-ref/project/shell.jsx Sidebar. */}
      <div className="sidebar-section">
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
            <button className="proj-select" type="button" disabled>
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
            <div className="proj-menu">
              {sites.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={
                    'proj-menu-item ' + (s.id === activeSiteId ? 'active' : '')
                  }
                  onClick={() => setActiveSite(s.id)}
                >
                  <span>{s.name || s.domain}</span>
                  <span className="proj-menu-count">{s.domain}</span>
                </button>
              ))}
              <div className="proj-menu-sep" />
              <button
                type="button"
                className="proj-menu-item"
                onClick={() => setShowAddSite(true)}
              >
                <Icon name="plus" size={12} />
                <span>Add site</span>
              </button>
            </div>
          </>
        )}

        {showAddSite && (
          <AddSiteModal onClose={() => setShowAddSite(false)} />
        )}
      </div>

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
