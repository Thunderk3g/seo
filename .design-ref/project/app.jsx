// app.jsx — root: state for crawl simulation, activity feed, system metrics,
// page routing.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#6ee7b7",
  "density": "regular",
  "showQuickStats": true,
  "crawlSpeed": 1.0,
  "theme": "dark"
}/*EDITMODE-END*/;

const ACCENT_PALETTES = {
  '#6ee7b7': { hover: '#34d399', glow: 'rgba(110, 231, 183, 0.18)', name: 'Mint' },     // mint-green
  '#22d3ee': { hover: '#06b6d4', glow: 'rgba(34, 211, 238, 0.18)', name: 'Cyan' },
  '#818cf8': { hover: '#6366f1', glow: 'rgba(129, 140, 248, 0.18)', name: 'Indigo' },
  '#f472b6': { hover: '#ec4899', glow: 'rgba(244, 114, 182, 0.18)', name: 'Magenta' },
  '#fbbf24': { hover: '#f59e0b', glow: 'rgba(251, 191, 36, 0.18)', name: 'Amber' },
};

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [page, setPage] = React.useState('dashboard');
  const [urlInput, setUrlInput] = React.useState('https://lumen.travel');
  const [selectedIssue, setSelectedIssue] = React.useState(ISSUES[0]);

  // Live crawl state.
  const [crawl, setCrawl] = React.useState(() => ({
    state: 'running',
    total: 2310,
    crawled: 1842,
    pending: 423,
    failed: 47,
    excluded: 312,
    rate: 55.2,
    avgMs: 1024,
    elapsed: '00:12:45',
    eta: '00:08:21',
    healthScore: 78,
    currentUrl: 'https://lumen.travel/journal/iceland-ring-road-7-days',
  }));

  const [activity, setActivity] = React.useState(() => seedActivity());
  const [metrics, setMetrics] = React.useState(() => ({
    rps: 55.2, queue: 423, threads: 24, memMb: 612,
    rpsHistory: Array.from({ length: 32 }, () => 50 + Math.random() * 12),
    queueHistory: Array.from({ length: 32 }, () => 400 + Math.random() * 60),
  }));

  // Crawl tick.
  React.useEffect(() => {
    const id = setInterval(() => {
      if (crawl.state !== 'running') return;
      setCrawl((c) => {
        const inc = Math.max(1, Math.round(2 * t.crawlSpeed + Math.random() * 3));
        const newCrawled = Math.min(c.total, c.crawled + inc);
        const newPending = Math.max(0, c.pending - Math.floor(inc * 0.8));
        const newFailed = c.failed + (Math.random() < 0.15 * t.crawlSpeed ? 1 : 0);
        const [m, s] = c.elapsed.split(':').slice(-2).map(Number);
        const totalSec = m * 60 + s + 1;
        const newElapsed = `00:${String(Math.floor(totalSec / 60)).padStart(2, '0')}:${String(totalSec % 60).padStart(2, '0')}`;
        const remaining = c.total - newCrawled;
        const etaSec = Math.round(remaining / Math.max(1, c.rate));
        const newEta = `00:${String(Math.floor(etaSec / 60)).padStart(2, '0')}:${String(etaSec % 60).padStart(2, '0')}`;
        const sample = URLS[Math.floor(Math.random() * URLS.length)];
        return { ...c, crawled: newCrawled, pending: newPending, failed: newFailed,
                 elapsed: newElapsed, eta: newEta, currentUrl: sample.url,
                 rate: 50 + Math.random() * 12 };
      });
    }, 1000);
    return () => clearInterval(id);
  }, [crawl.state, t.crawlSpeed]);

  // Activity feed tick.
  React.useEffect(() => {
    const id = setInterval(() => {
      if (crawl.state !== 'running') return;
      setActivity((a) => [makeActivityEntry(), ...a].slice(0, 14));
    }, Math.max(400, 1400 / t.crawlSpeed));
    return () => clearInterval(id);
  }, [crawl.state, t.crawlSpeed]);

  // System metrics tick.
  React.useEffect(() => {
    const id = setInterval(() => {
      setMetrics((m) => {
        const newRps = Math.max(0, m.rps + (Math.random() - 0.5) * 6);
        const newQ = Math.max(0, m.queue + Math.round((Math.random() - 0.5) * 30));
        return {
          rps: newRps,
          queue: newQ,
          threads: Math.max(8, Math.min(32, m.threads + (Math.random() < 0.3 ? (Math.random() < 0.5 ? -1 : 1) : 0))),
          memMb: Math.max(200, Math.min(1800, m.memMb + Math.round((Math.random() - 0.45) * 30))),
          rpsHistory: [...m.rpsHistory.slice(1), newRps],
          queueHistory: [...m.queueHistory.slice(1), newQ],
        };
      });
    }, 800);
    return () => clearInterval(id);
  }, []);

  const onAction = (action) => {
    if (action === 'start') setCrawl((c) => ({ ...c, state: 'running' }));
    if (action === 'pause') setCrawl((c) => ({ ...c, state: 'paused' }));
    if (action === 'stop')  setCrawl((c) => ({ ...c, state: 'idle' }));
  };

  // Apply theme variables.
  const accentMeta = ACCENT_PALETTES[t.accent] || ACCENT_PALETTES['#6ee7b7'];
  React.useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--accent', t.accent);
    root.style.setProperty('--accent-hover', accentMeta.hover);
    root.style.setProperty('--accent-glow', accentMeta.glow);
    root.dataset.density = t.density;
    root.dataset.theme = t.theme;
  }, [t.accent, t.density, t.theme, accentMeta.hover, accentMeta.glow]);

  const onIssueSelect = (issue) => {
    setSelectedIssue(issue);
    setPage('issues');
  };

  const project = PROJECTS[0];

  return (
    <div className="app-shell">
      <Sidebar active={page} onNav={setPage} project={project}
               showQuickStats={t.showQuickStats} crawl={crawl} />
      <div className="app-main">
        <TopBar project={project} crawl={crawl} onAction={onAction}
                urlInput={urlInput} setUrlInput={setUrlInput} />
        <main className="content-scroll">
          {page === 'dashboard' && (
            <DashboardPage crawl={crawl} activity={activity} metrics={metrics}
                           onIssueSelect={onIssueSelect} onNav={setPage} />
          )}
          {page === 'sessions' && <SessionsPage />}
          {page === 'pages' && <PagesUrlsPage onIssueSelect={onIssueSelect} />}
          {page === 'issues' && (
            <IssuesPage selectedIssue={selectedIssue} setSelectedIssue={setSelectedIssue} />
          )}
          {page === 'analytics' && <AnalyticsPage />}
          {page === 'visualizations' && <VisualizationsPage />}
          {page === 'exports' && <ExportsPage />}
          {page === 'settings' && <SettingsPage />}
        </main>
        <footer className="status-bar">
          <span><span className="status-dot" /> Connected to LatticeBot/2.4</span>
          <span className="text-muted">·</span>
          <span>Last crawl May 6, 2026 13:30 IST</span>
          <span className="text-muted">·</span>
          <span>Crawl type <b>Deep crawl</b></span>
          <span className="text-muted">·</span>
          <span>User agent <b className="mono">LatticeBot/2.4</b></span>
          <span style={{ flex: 1 }} />
          <span className="status-online"><span className="status-dot" /> All systems operational</span>
        </footer>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Theme">
          <TweakColor label="Accent" value={t.accent}
                      options={Object.keys(ACCENT_PALETTES)}
                      onChange={(v) => setTweak('accent', v)} />
          <TweakRadio label="Density" value={t.density}
                      options={['compact', 'regular', 'comfy']}
                      onChange={(v) => setTweak('density', v)} />
          <TweakRadio label="Mode" value={t.theme}
                      options={['dark', 'light']}
                      onChange={(v) => setTweak('theme', v)} />
        </TweakSection>
        <TweakSection label="Crawl simulation">
          <TweakSlider label="Speed" value={t.crawlSpeed}
                       min={0.25} max={3} step={0.25} unit="×"
                       onChange={(v) => setTweak('crawlSpeed', v)} />
          <TweakToggle label="Sidebar quick-stats" value={t.showQuickStats}
                       onChange={(v) => setTweak('showQuickStats', v)} />
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <TweakButton label="Start" onClick={() => onAction('start')} />
            <TweakButton label="Pause" secondary onClick={() => onAction('pause')} />
            <TweakButton label="Stop" secondary onClick={() => onAction('stop')} />
          </div>
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

function seedActivity() {
  const out = [];
  for (let i = 0; i < 8; i++) out.push(makeActivityEntry(i));
  return out;
}

function makeActivityEntry(seed) {
  const url = URLS[Math.floor(Math.random() * URLS.length)];
  const kinds = [
    { kind: 'crawl', verb: 'Crawling', status: null },
    { kind: 'ok', verb: '200 OK', status: 200 },
    { kind: 'meta', verb: 'Extracted metadata', status: 200 },
    { kind: 'links', verb: `Found ${Math.floor(Math.random() * 30) + 4} links`, status: null },
    { kind: 'image', verb: 'Indexed image', status: 200 },
  ];
  const errors = [
    { kind: 'redirect', verb: '301 redirect', status: 301 },
    { kind: '404', verb: '404 Not Found', status: 404 },
  ];
  const pool = url.status === 200 ? kinds : url.status >= 400 ? errors : kinds;
  const t = pool[Math.floor(Math.random() * pool.length)];
  const now = new Date();
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
  return {
    id: Math.random().toString(36).slice(2) + (seed || ''),
    kind: t.kind, verb: t.verb, status: t.status, time,
    url: url.url,
  };
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
