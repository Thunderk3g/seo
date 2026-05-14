// Sidebar.tsx — left rail of the Bajaj SEO dashboard.
//
// Reshaped around the SEO AI grading flow: Overview + SEO Grade are
// the primary surfaces. The "Data Sources" group surfaces the raw
// inputs that feed the agents (Search Console, SEMrush, AEM sitemap)
// as standalone dashboards. The embedded Crawler Engine (v2) sits in
// its own group below.

import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'wouter';
import Icon from './icons/Icon';
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

const PRIMARY_NAV: NavItem[] = [
  { id: 'overview', label: 'Overview', icon: 'dashboard', path: '/' },
  { id: 'grade', label: 'SEO Grade', icon: 'analytics', path: '/grade' },
  { id: 'pages', label: 'Pages / URLs', icon: 'pages', path: '/pages' },
  { id: 'issues', label: 'Issues', icon: 'issues', path: '/issues' },
];

const DATA_SOURCE_NAV: NavItem[] = [
  { id: 'gsc', label: 'Search Console', icon: 'analytics', path: '/gsc' },
  { id: 'semrush', label: 'SEMrush Keywords', icon: 'pages', path: '/semrush' },
  { id: 'sitemap', label: 'Content via Sitemap', icon: 'visualizations', path: '/sitemap' },
  { id: 'competitors', label: 'Competitor Gap', icon: 'issues', path: '/competitors' },
];

// Embedded Crawler Engine (v2) — backed by the standalone FastAPI service in
// crawler-engine/ (proxied at /crawler-api). See src/crawler/*.
const CRAWLER_NAV: NavItem[] = [
  { id: 'crawler-dash', label: 'Crawler Dashboard', icon: 'globe', path: '/crawler' },
  { id: 'crawler-tree', label: 'Site Tree', icon: 'visualizations', path: '/crawler/tree' },
  { id: 'crawler-logs', label: 'Live Logs', icon: 'zap', path: '/crawler/logs' },
  { id: 'crawler-reports', label: 'Reports', icon: 'pages', path: '/crawler/reports' },
  { id: 'crawler-settings', label: 'Crawler Settings', icon: 'settings', path: '/crawler/settings' },
];

function isActive(path: string, current: string): boolean {
  if (path === '/') return current === '/';
  return current === path || current.startsWith(path + '/');
}

export default function Sidebar() {
  const [location] = useLocation();
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
        <img
          src="/bajaj-logo.webp"
          alt="Bajaj Life Insurance"
          className="brand-logo"
        />
        <div className="brand-sub-line">AI Grading Console</div>
      </div>

      <nav className="sidebar-nav">
        {PRIMARY_NAV.map((it) => (
          <Link
            key={it.id}
            href={it.path}
            className={
              'nav-item ' +
              (isActive(it.path, location) ||
              (it.path === '/grade' && location.startsWith('/grade'))
                ? 'active'
                : '')
            }
          >
            <Icon name={it.icon} size={16} />
            <span>{it.label}</span>
            {it.id === 'issues' && errorIssueCount > 0 && (
              <span className="nav-badge">{errorIssueCount}</span>
            )}
          </Link>
        ))}
      </nav>

      <div className="sidebar-section" style={{ marginTop: 10 }}>
        <div className="sidebar-section-title">Data Sources</div>
        <nav className="sidebar-nav">
          {DATA_SOURCE_NAV.map((it) => (
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
      </div>

      {/* Embedded Crawler Engine (v2) — separate FastAPI service, proxied at /crawler-api. */}
      <div className="sidebar-section" style={{ marginTop: 10 }}>
        <div className="sidebar-section-title">Crawler Engine</div>
        <nav className="sidebar-nav">
          {CRAWLER_NAV.map((it) => {
            const active =
              it.path === '/crawler'
                ? location === '/crawler'
                : location === it.path || location.startsWith(it.path + '/');
            return (
              <Link key={it.id} href={it.path} className={'nav-item ' + (active ? 'active' : '')}>
                <Icon name={it.icon} size={16} />
                <span>{it.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      {!websites.isLoading && sites.length > 0 && (
        <div className="sidebar-section" ref={projPickerRef}>
          <div className="sidebar-section-title">Project</div>
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
            </div>
          )}
        </div>
      )}

      {/* Quick stats — only renders when there's a session to summarise. */}
      <QuickStats sessionId={latestSessionId} />

      <div style={{ flex: 1 }} />
    </aside>
  );
}
