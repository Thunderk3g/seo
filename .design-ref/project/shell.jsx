// shell.jsx — sidebar, topbar, layout shell, navigation routing.

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { id: 'sessions', label: 'Crawl Sessions', icon: 'sessions' },
  { id: 'pages', label: 'Pages / URLs', icon: 'pages' },
  { id: 'issues', label: 'Issues', icon: 'issues' },
  { id: 'analytics', label: 'Analytics', icon: 'analytics' },
  { id: 'visualizations', label: 'Visualizations', icon: 'visualizations' },
  { id: 'exports', label: 'Exports', icon: 'exports' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
];

function Sidebar({ active, onNav, project, showQuickStats, crawl }) {
  const [projOpen, setProjOpen] = React.useState(false);
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark"><BrandMark size={20} color="var(--accent)" /></div>
        <div>
          <div className="brand-name">Lattice</div>
          <div className="brand-sub">SEO Crawler</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((it) => (
          <button key={it.id}
                  className={'nav-item ' + (active === it.id ? 'active' : '')}
                  onClick={() => onNav(it.id)}>
            <Icon name={it.icon} size={16} />
            <span>{it.label}</span>
            {it.id === 'issues' && (
              <span className="nav-badge">{ISSUES.reduce((s, i) => s + (i.severity === 'error' ? i.count : 0), 0)}</span>
            )}
          </button>
        ))}
      </nav>

      <div className="sidebar-section">
        <div className="sidebar-section-title">Project</div>
        <button className="proj-select" onClick={() => setProjOpen(!projOpen)}>
          <div className="proj-info">
            <div className="proj-name">{project.name}</div>
            <div className="proj-sub">{project.urls.toLocaleString()} URLs</div>
          </div>
          <Icon name="chevDown" size={14} />
        </button>
        {projOpen && (
          <div className="proj-menu">
            {PROJECTS.map((p) => (
              <button key={p.id} className={'proj-menu-item ' + (p.id === project.id ? 'active' : '')}>
                <span>{p.name}</span>
                <span className="proj-menu-count">{p.urls.toLocaleString()}</span>
              </button>
            ))}
            <div className="proj-menu-sep" />
            <button className="proj-menu-item">
              <Icon name="plus" size={12} />
              <span>New project</span>
            </button>
          </div>
        )}
      </div>

      {showQuickStats && (
        <div className="sidebar-section">
          <div className="sidebar-section-title">Quick stats</div>
          <div className="quick-stats">
            <div className="qs-row"><span>Total URLs</span><b>{crawl.total.toLocaleString()}</b></div>
            <div className="qs-row"><span>Crawled</span><b>{crawl.crawled.toLocaleString()}</b></div>
            <div className="qs-row"><span>Pending</span><b>{crawl.pending.toLocaleString()}</b></div>
            <div className="qs-row"><span>Errors</span><b className="qs-err">{crawl.failed}</b></div>
            <div className="qs-row"><span>Crawl rate</span><b>{crawl.rate.toFixed(1)} URLs/s</b></div>
            <div className="qs-row"><span>Avg. response</span><b>{Math.round(crawl.avgMs)} ms</b></div>
            <div className="qs-row"><span>Elapsed</span><b style={{ fontVariantNumeric: 'tabular-nums' }}>{crawl.elapsed}</b></div>
          </div>
        </div>
      )}

      <div style={{ flex: 1 }} />

      <div className="sidebar-user">
        <div className="user-avatar">AV</div>
        <div className="user-info">
          <div className="user-name">Aman Verma</div>
          <div className="user-role">Administrator</div>
        </div>
        <button className="icon-btn" aria-label="Account menu"><Icon name="more" size={14} /></button>
      </div>
    </aside>
  );
}

function TopBar({ project, crawl, onAction, urlInput, setUrlInput }) {
  return (
    <header className="topbar">
      <div className="topbar-row">
        <div className="topbar-controls">
          <div className="url-field">
            <Icon name="globe" size={14} />
            <input type="text" value={urlInput}
                   onChange={(e) => setUrlInput(e.target.value)}
                   placeholder="https://example.com" />
            <span className="url-field-hint">⌘K</span>
          </div>
          <button className={'btn primary ' + (crawl.state === 'running' ? 'btn-disabled' : '')}
                  onClick={() => onAction('start')}
                  disabled={crawl.state === 'running'}>
            <Icon name="play" size={11} />
            <span>{crawl.state === 'running' ? 'Crawling…' : 'Start crawl'}</span>
          </button>
          <button className="btn ghost" onClick={() => onAction('pause')}
                  disabled={crawl.state !== 'running'}>
            <Icon name="pause" size={11} />
            <span>Pause</span>
          </button>
          <button className="btn ghost" onClick={() => onAction('stop')}
                  disabled={crawl.state === 'idle'}>
            <Icon name="stop" size={11} />
            <span>Stop</span>
          </button>
        </div>

        <div className="topbar-actions">
          <button className="icon-btn" aria-label="Search"><Icon name="search" size={15} /></button>
          <button className="icon-btn" aria-label="Refresh"><Icon name="refresh" size={15} /></button>
          <button className="icon-btn icon-btn-badge" aria-label="Notifications">
            <Icon name="bell" size={15} />
            <span className="dot" />
          </button>
          <div className="topbar-divider" />
          <button className="icon-btn" aria-label="Settings"><Icon name="settings" size={15} /></button>
        </div>
      </div>

      {crawl.state !== 'idle' && (
        <div className="topbar-progress">
          <div className="progress-meta">
            <span className={'crawl-state-pill ' + crawl.state}>
              <span className="state-dot" />
              {crawl.state === 'running' ? 'Crawling' : crawl.state === 'paused' ? 'Paused' : 'Stopped'}
            </span>
            <span className="progress-current">{crawl.currentUrl}</span>
          </div>
          <div className="progress-stats">
            <span><b>{crawl.crawled.toLocaleString()}</b> / {crawl.total.toLocaleString()}</span>
            <span className="text-muted">·</span>
            <span><b>{Math.round((crawl.crawled / crawl.total) * 100)}%</b></span>
            <span className="text-muted">·</span>
            <span>elapsed <b style={{ fontVariantNumeric: 'tabular-nums' }}>{crawl.elapsed}</b></span>
            <span className="text-muted">·</span>
            <span>ETA <b style={{ fontVariantNumeric: 'tabular-nums' }}>{crawl.eta}</b></span>
          </div>
          <div className="progress-track">
            <div className="progress-fill"
                 style={{ width: `${(crawl.crawled / crawl.total) * 100}%` }} />
          </div>
        </div>
      )}
    </header>
  );
}

Object.assign(window, { Sidebar, TopBar, NAV_ITEMS });
