// pages.jsx — non-dashboard pages: Sessions, Pages/URLs, Issues, Analytics,
// Visualizations, Exports, Settings.

// ── Pages / URLs ─────────────────────────────────────────────────────────────
function PagesUrlsPage({ onIssueSelect }) {
  const [tab, setTab] = React.useState('all');
  const [query, setQuery] = React.useState('');
  const [sort, setSort] = React.useState({ key: 'depth', dir: 'asc' });
  const [statusFilter, setStatusFilter] = React.useState('all');
  const [page, setPage] = React.useState(1);
  const PAGE_SIZE = 25;

  const tabs = [
    { id: 'all', label: 'All', count: URLS.length },
    { id: 'html', label: 'HTML', count: URLS.filter((u) => u.contentType === 'html').length },
    { id: 'images', label: 'Images', count: URLS.filter((u) => u.contentType === 'image').length },
    { id: '4xx', label: '4xx', count: URLS.filter((u) => u.status >= 400 && u.status < 500).length },
    { id: '3xx', label: '3xx', count: URLS.filter((u) => u.status >= 300 && u.status < 400).length },
    { id: '5xx', label: '5xx', count: URLS.filter((u) => u.status >= 500).length },
  ];

  const filtered = React.useMemo(() => {
    let r = URLS;
    if (tab === 'html') r = r.filter((u) => u.contentType === 'html');
    else if (tab === 'images') r = r.filter((u) => u.contentType === 'image');
    else if (tab === '4xx') r = r.filter((u) => u.status >= 400 && u.status < 500);
    else if (tab === '3xx') r = r.filter((u) => u.status >= 300 && u.status < 400);
    else if (tab === '5xx') r = r.filter((u) => u.status >= 500);
    if (statusFilter !== 'all') r = r.filter((u) => String(u.status).startsWith(statusFilter[0]));
    if (query) {
      const q = query.toLowerCase();
      r = r.filter((u) => u.path.toLowerCase().includes(q)
                      || (u.title || '').toLowerCase().includes(q));
    }
    r = r.slice().sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key];
      if (typeof av === 'number') return sort.dir === 'asc' ? av - bv : bv - av;
      return sort.dir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return r;
  }, [tab, query, sort, statusFilter]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const slice = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  React.useEffect(() => { setPage(1); }, [tab, query, sort, statusFilter]);

  const setSortKey = (k) => setSort((s) => ({ key: k, dir: s.key === k && s.dir === 'asc' ? 'desc' : 'asc' }));
  const sortIcon = (k) => sort.key === k ? (
    <Icon name={sort.dir === 'asc' ? 'arrowUp' : 'arrowDown'} size={10} />
  ) : null;

  return (
    <div className="page-grid">
      <PageHeader title="Pages / URLs"
        subtitle={`${URLS.length.toLocaleString()} URLs from ${SITE} · last crawled May 6, 2026`}
        actions={
          <>
            <button className="btn ghost"><Icon name="filter" size={11} /><span>Advanced filters</span></button>
            <button className="btn ghost"><Icon name="download" size={11} /><span>Export CSV</span></button>
            <button className="btn primary"><Icon name="refresh" size={11} /><span>Re-crawl</span></button>
          </>
        }
      />

      <div className="card big-table">
        <div className="card-head card-head-flex">
          <div className="tabs">
            {tabs.map((t) => (
              <button key={t.id} className={'tab ' + (t.id === tab ? 'active' : '')}
                      onClick={() => setTab(t.id)}>
                {t.label} <span className="tab-count">{t.count.toLocaleString()}</span>
              </button>
            ))}
          </div>
          <div className="table-toolbar">
            <div className="search-field small">
              <Icon name="search" size={13} />
              <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                     placeholder="Search URL or title…" />
            </div>
            <select className="select-field" value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">Any status</option>
              <option value="2xx">2xx</option>
              <option value="3xx">3xx</option>
              <option value="4xx">4xx</option>
              <option value="5xx">5xx</option>
            </select>
            <button className="icon-btn"><Icon name="more" size={14} /></button>
          </div>
        </div>

        <div className="big-url-table">
          <div className="bt-row bt-head">
            <div className="bt-num">#</div>
            <div className="bt-url" onClick={() => setSortKey('path')}>URL {sortIcon('path')}</div>
            <div className="bt-status" onClick={() => setSortKey('status')}>Status {sortIcon('status')}</div>
            <div className="bt-title" onClick={() => setSortKey('title')}>Title {sortIcon('title')}</div>
            <div className="bt-meta">Meta description</div>
            <div className="bt-num2" onClick={() => setSortKey('depth')}>Depth {sortIcon('depth')}</div>
            <div className="bt-num2" onClick={() => setSortKey('inlinks')}>In {sortIcon('inlinks')}</div>
            <div className="bt-num2" onClick={() => setSortKey('outlinks')}>Out {sortIcon('outlinks')}</div>
            <div className="bt-num2" onClick={() => setSortKey('responseTime')}>Resp {sortIcon('responseTime')}</div>
            <div className="bt-num2" onClick={() => setSortKey('size')}>Size {sortIcon('size')}</div>
          </div>
          {slice.map((u, i) => (
            <div key={u.id} className="bt-row">
              <div className="bt-num">{(page - 1) * PAGE_SIZE + i + 1}</div>
              <div className="bt-url">
                <span className="bt-url-link" title={u.url}>{u.path}</span>
              </div>
              <div className="bt-status"><span className={'status-pill s' + Math.floor(u.status / 100)}>{u.status}</span></div>
              <div className="bt-title" title={u.title}>{u.title || <span className="text-muted-i">— missing —</span>}</div>
              <div className="bt-meta" title={u.meta}>{u.meta || <span className="text-muted-i">— missing —</span>}</div>
              <div className="bt-num2">{u.depth}</div>
              <div className="bt-num2">{u.inlinks}</div>
              <div className="bt-num2">{u.outlinks}</div>
              <div className="bt-num2">{Math.round(u.responseTime)}<span className="text-muted">ms</span></div>
              <div className="bt-num2">{u.size.toFixed(1)}<span className="text-muted">KB</span></div>
            </div>
          ))}
        </div>

        <div className="table-foot">
          <span className="text-muted">
            {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, filtered.length).toLocaleString()}
            {' '}of {filtered.length.toLocaleString()}
          </span>
          <div className="pager">
            <button className="icon-btn" disabled={page === 1} onClick={() => setPage(page - 1)}>
              <Icon name="chevLeft" size={14} />
            </button>
            {pagerNumbers(page, totalPages).map((n, i) =>
              n === '…' ? <span key={i} className="pager-dot">…</span> :
              <button key={i} className={'pager-num ' + (n === page ? 'active' : '')}
                      onClick={() => setPage(n)}>{n}</button>
            )}
            <button className="icon-btn" disabled={page === totalPages} onClick={() => setPage(page + 1)}>
              <Icon name="chevRight" size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function pagerNumbers(p, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (p <= 3) return [1, 2, 3, 4, '…', total];
  if (p >= total - 2) return [1, '…', total - 3, total - 2, total - 1, total];
  return [1, '…', p - 1, p, p + 1, '…', total];
}

// ── Issues ───────────────────────────────────────────────────────────────────
function IssuesPage({ selectedIssue, setSelectedIssue }) {
  const [sevFilter, setSevFilter] = React.useState('all');
  const filtered = sevFilter === 'all' ? ISSUES : ISSUES.filter((i) => i.severity === sevFilter);
  const sel = selectedIssue || filtered[0];
  return (
    <div className="page-grid">
      <PageHeader title="Issues"
        subtitle={`${ISSUES.reduce((s, i) => s + i.count, 0).toLocaleString()} issues across 12 categories`}
        actions={
          <>
            <button className="btn ghost"><Icon name="download" size={11} /><span>Export</span></button>
            <button className="btn ghost"><Icon name="filter" size={11} /><span>Configure rules</span></button>
          </>
        }
      />
      <div className="row issues-row">
        <div className="card issues-list-card">
          <div className="card-head card-head-flex">
            <h3>All issues</h3>
            <div className="tabs small">
              {['all', 'error', 'warning', 'notice'].map((s) => (
                <button key={s} className={'tab ' + (s === sevFilter ? 'active' : '')}
                        onClick={() => setSevFilter(s)}>
                  {s === 'all' ? 'All' : s[0].toUpperCase() + s.slice(1) + 's'}
                </button>
              ))}
            </div>
          </div>
          <div className="issues-list">
            {filtered.map((i) => (
              <button key={i.id}
                      className={'issue-list-item ' + (sel?.id === i.id ? 'active' : '')}
                      onClick={() => setSelectedIssue(i)}>
                <span className={'sev-bar sev-' + i.severity} />
                <div className="issue-list-body">
                  <div className="issue-list-head">
                    <span className="issue-list-name">{i.name}</span>
                    <span className="issue-list-count">{i.count.toLocaleString()}</span>
                  </div>
                  <div className="issue-list-desc">{i.description}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
        <div className="card issue-detail-card">
          {sel && (
            <>
              <div className="issue-detail-head">
                <div>
                  <div className="issue-detail-eyebrow">
                    <span className={'sev-pill sev-' + sel.severity}>{sel.severity}</span>
                    <span className="text-muted">·</span>
                    <span className="text-muted">{sel.count.toLocaleString()} affected URLs</span>
                  </div>
                  <h2 className="issue-detail-title">{sel.name}</h2>
                  <p className="issue-detail-desc">{sel.description}</p>
                </div>
                <div className="issue-detail-actions">
                  <button className="btn ghost"><Icon name="copy" size={11} /><span>Copy list</span></button>
                  <button className="btn ghost"><Icon name="download" size={11} /><span>Export</span></button>
                </div>
              </div>
              <div className="issue-affected">
                <div className="issue-affected-head">
                  <span>URL</span>
                  <span>Status</span>
                  <span>Inlinks</span>
                  <span>Resp.</span>
                  <span></span>
                </div>
                <div className="issue-affected-list">
                  {sel.urls.slice(0, 30).map((u) => (
                    <div key={u.id} className="issue-affected-row">
                      <div className="issue-affected-url">{u.path}</div>
                      <div><span className={'status-pill s' + Math.floor(u.status / 100)}>{u.status}</span></div>
                      <div className="num">{u.inlinks}</div>
                      <div className="num">{Math.round(u.responseTime)}ms</div>
                      <div><button className="icon-btn"><Icon name="external" size={12} /></button></div>
                    </div>
                  ))}
                  {sel.urls.length > 30 && (
                    <div className="issue-affected-more">
                      + {(sel.urls.length - 30).toLocaleString()} more affected URLs
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Crawl Sessions ───────────────────────────────────────────────────────────
function SessionsPage() {
  return (
    <div className="page-grid">
      <PageHeader title="Crawl sessions"
        subtitle={`${SESSIONS.length} sessions for ${SITE} · weekly schedule active`}
        actions={
          <>
            <button className="btn ghost"><Icon name="history" size={11} /><span>Schedule</span></button>
            <button className="btn primary"><Icon name="play" size={11} /><span>New crawl</span></button>
          </>
        }
      />
      <div className="card">
        <div className="sessions-table">
          <div className="sess-row sess-head">
            <div>Session</div><div>Started</div><div>Type</div><div>Status</div>
            <div className="num">URLs</div><div className="num">Errors</div>
            <div className="num">Warnings</div><div>Duration</div><div></div>
          </div>
          {SESSIONS.map((s) => (
            <div key={s.id} className="sess-row">
              <div className="sess-id">{s.id}</div>
              <div className="text-muted-2">{s.started}</div>
              <div>{s.type}</div>
              <div>
                <span className={'sess-status sess-' + s.status}>
                  <span className="state-dot" />
                  {s.status === 'running' ? 'Running' : s.status === 'failed' ? 'Failed' : 'Completed'}
                </span>
              </div>
              <div className="num">{s.urls.toLocaleString()}<span className="text-muted">/{s.total.toLocaleString()}</span></div>
              <div className="num"><span style={{ color: s.errors > 30 ? '#f87171' : 'inherit' }}>{s.errors}</span></div>
              <div className="num">{s.warnings}</div>
              <div className="text-muted-2" style={{ fontVariantNumeric: 'tabular-nums' }}>{s.duration}</div>
              <div><button className="icon-btn"><Icon name="more" size={14} /></button></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Analytics ────────────────────────────────────────────────────────────────
function AnalyticsPage() {
  const statusData = [
    { label: '200', value: URLS.filter((u) => u.status === 200).length, color: 'var(--accent)' },
    { label: '301', value: URLS.filter((u) => u.status === 301).length, color: '#60a5fa' },
    { label: '302', value: URLS.filter((u) => u.status === 302).length, color: '#a78bfa' },
    { label: '404', value: URLS.filter((u) => u.status === 404).length, color: '#f87171' },
    { label: '410', value: URLS.filter((u) => u.status === 410).length, color: '#fb923c' },
    { label: '500', value: URLS.filter((u) => u.status === 500).length, color: '#fbbf24' },
    { label: '503', value: URLS.filter((u) => u.status === 503).length, color: '#fde047' },
  ].filter((d) => d.value > 0);

  const depthData = Array.from({ length: 8 }, (_, i) => ({
    label: i === 0 ? '/' : 'd' + i,
    value: URLS.filter((u) => u.depth === i).length,
    color: 'var(--accent)',
  }));

  const respBuckets = [
    [0, 100, '<100'], [100, 250, '100–250'], [250, 500, '250–500'],
    [500, 1000, '500ms–1s'], [1000, 2000, '1–2s'], [2000, 9999, '>2s']
  ];
  const respData = respBuckets.map(([lo, hi, label]) => ({
    label, value: URLS.filter((u) => u.responseTime >= lo && u.responseTime < hi).length,
    color: hi > 1000 ? (hi > 2000 ? '#f87171' : '#fbbf24') : 'var(--accent)',
  }));

  const ctData = [
    { label: 'HTML', value: URLS.filter((u) => u.contentType === 'html').length, color: 'var(--accent)' },
    { label: 'Images', value: URLS.filter((u) => u.contentType === 'image').length, color: '#60a5fa' },
  ];

  return (
    <div className="page-grid">
      <PageHeader title="Analytics" subtitle="Distribution of pages, response codes, and size across the crawl." />
      <div className="row analytics-row">
        <div className="card">
          <div className="card-head"><h3>Status code distribution</h3></div>
          <div className="analytics-chart-body">
            <Donut segments={statusData} size={170} thickness={18}
                   label={URLS.length.toLocaleString()} sublabel="URLs" />
            <div className="legend">
              {statusData.map((s) => (
                <div key={s.label} className="legend-row">
                  <span className="dot-sm" style={{ background: s.color }} />
                  <span className="legend-label">{s.label}</span>
                  <span className="legend-value">{s.value.toLocaleString()}</span>
                  <span className="legend-pct">{((s.value / URLS.length) * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h3>Crawl depth distribution</h3></div>
          <BarChart data={depthData} height={210} />
        </div>
      </div>
      <div className="row analytics-row">
        <div className="card">
          <div className="card-head"><h3>Response time</h3></div>
          <BarChart data={respData} height={210} />
        </div>
        <div className="card">
          <div className="card-head"><h3>Content types</h3></div>
          <div className="analytics-chart-body">
            <Donut segments={ctData} size={170} thickness={18}
                   label={URLS.length.toLocaleString()} sublabel="URLs" />
            <div className="legend">
              {ctData.map((s) => (
                <div key={s.label} className="legend-row">
                  <span className="dot-sm" style={{ background: s.color }} />
                  <span className="legend-label">{s.label}</span>
                  <span className="legend-value">{s.value.toLocaleString()}</span>
                  <span className="legend-pct">{((s.value / URLS.length) * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Visualizations: tree + network graph + treemap ──────────────────────────
function VisualizationsPage() {
  const [tab, setTab] = React.useState('graph');
  return (
    <div className="page-grid">
      <PageHeader title="Visualizations" subtitle={`Visual structure of ${SITE} — explore by graph, tree, or treemap.`}
        actions={
          <div className="tabs">
            {[
              ['graph', 'Network graph'],
              ['tree', 'Site tree'],
              ['treemap', 'Treemap'],
            ].map(([id, label]) => (
              <button key={id} className={'tab ' + (id === tab ? 'active' : '')}
                      onClick={() => setTab(id)}>{label}</button>
            ))}
          </div>
        }
      />
      {tab === 'graph' && <NetworkGraph />}
      {tab === 'tree' && <SiteTree />}
      {tab === 'treemap' && <Treemap />}
    </div>
  );
}

function NetworkGraph() {
  // Pre-computed force-directed layout (deterministic). Nodes by depth ring.
  const W = 980, H = 560;
  const cx = W / 2, cy = H / 2;
  const nodes = React.useMemo(() => {
    const root = { id: 'root', label: '/', depth: 0, x: cx, y: cy, r: 14, color: 'var(--accent)' };
    const lvl1 = ['destinations', 'experiences', 'journal', 'about', 'help', 'account', 'legal'];
    const out = [root];
    lvl1.forEach((name, i) => {
      const a = (i / lvl1.length) * Math.PI * 2 - Math.PI / 2;
      out.push({ id: 'l1-' + name, label: name, depth: 1,
        x: cx + Math.cos(a) * 130, y: cy + Math.sin(a) * 130,
        r: 9, color: 'rgba(255,255,255,0.85)' });
      const childCount = name === 'destinations' ? 12 : name === 'journal' ? 9 : 5;
      for (let j = 0; j < childCount; j++) {
        const a2 = a + (j - childCount / 2) * 0.07;
        const dist = 230 + (j % 2) * 30;
        out.push({ id: `l2-${name}-${j}`, label: '', depth: 2,
          x: cx + Math.cos(a2) * dist, y: cy + Math.sin(a2) * dist,
          parent: 'l1-' + name,
          r: 4 + (j % 3),
          color: j === 4 && name === 'old' ? '#f87171' : 'rgba(126, 232, 209, 0.7)' });
        // Sometimes a leaf child.
        if (j % 3 === 0) {
          out.push({ id: `l3-${name}-${j}`, depth: 3,
            x: cx + Math.cos(a2 + 0.02) * (dist + 50),
            y: cy + Math.sin(a2 + 0.02) * (dist + 50),
            parent: `l2-${name}-${j}`, r: 2.5,
            color: 'rgba(255,255,255,0.35)' });
        }
      }
    });
    // Stray broken links.
    out.push({ id: 'broken-1', label: '/old/promo', depth: 2,
      x: cx + 350, y: cy - 200, r: 5, color: '#f87171' });
    out.push({ id: 'broken-2', label: '/blog/2019/welcome', depth: 2,
      x: cx - 380, y: cy + 180, r: 5, color: '#f87171' });
    return out;
  }, []);
  const edges = React.useMemo(() => {
    const list = [];
    for (const n of nodes) {
      if (n.parent) {
        const p = nodes.find((m) => m.id === n.parent);
        if (p) list.push({ a: p, b: n, broken: n.color === '#f87171' });
      } else if (n.depth === 1) {
        list.push({ a: nodes[0], b: n });
      }
    }
    // Cross-links for realism.
    list.push({ a: nodes[1], b: nodes.find((n) => n.id === 'l1-experiences'), kind: 'cross' });
    list.push({ a: nodes[1], b: nodes.find((n) => n.id === 'l1-journal'), kind: 'cross' });
    return list;
  }, [nodes]);

  return (
    <div className="card vis-card">
      <div className="card-head">
        <h3>Network graph</h3>
        <div className="vis-legend">
          <span><span className="dot-sm" style={{ background: 'var(--accent)' }} /> Crawled</span>
          <span><span className="dot-sm" style={{ background: '#f87171' }} /> Broken</span>
          <span><span className="dot-sm" style={{ background: 'rgba(255,255,255,0.5)' }} /> Linked</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="vis-svg" preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="rg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(126, 232, 209, 0.08)" />
            <stop offset="100%" stopColor="rgba(126, 232, 209, 0)" />
          </radialGradient>
        </defs>
        <circle cx={cx} cy={cy} r="240" fill="url(#rg)" />
        {edges.map((e, i) => (
          <line key={i} x1={e.a.x} y1={e.a.y} x2={e.b.x} y2={e.b.y}
                stroke={e.broken ? '#f87171' : e.kind === 'cross' ? 'rgba(126, 232, 209, 0.18)' : 'rgba(255,255,255,0.13)'}
                strokeWidth={e.kind === 'cross' ? 0.6 : 0.8}
                strokeDasharray={e.kind === 'cross' ? '3 3' : undefined} />
        ))}
        {nodes.map((n, i) => (
          <g key={n.id} className="vis-node" style={{ animationDelay: `${(i % 50) * 14}ms` }}>
            <circle cx={n.x} cy={n.y} r={n.r} fill={n.color}
                    stroke="rgba(0,0,0,0.4)" strokeWidth="0.5" />
            {n.depth <= 1 && n.label && (
              <text x={n.x} y={n.y + n.r + 12} textAnchor="middle"
                    fontSize="10.5" fill="rgba(255,255,255,0.7)"
                    fontFamily="ui-sans-serif">{n.label}</text>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}

function SiteTree() {
  return (
    <div className="card">
      <div className="card-head"><h3>Site tree</h3></div>
      <div className="tree-full">
        <TreeNode node={TREE} depth={0} initiallyOpen />
      </div>
    </div>
  );
}

function TreeNode({ node, depth, initiallyOpen }) {
  const [open, setOpen] = React.useState(initiallyOpen ?? depth < 2);
  const hasChildren = node.children && node.children.length > 0;
  return (
    <>
      <button className="tree-row" style={{ paddingLeft: 12 + depth * 18 }}
              onClick={() => hasChildren && setOpen(!open)}>
        {hasChildren ? (
          <Icon name="chevRight" size={11}
                style={{ transform: `rotate(${open ? 90 : 0}deg)`, transition: 'transform 0.15s', opacity: 0.5 }} />
        ) : <span style={{ width: 11, display: 'inline-block' }} />}
        <Icon name={hasChildren ? 'folder' : 'file'} size={13}
              style={{ color: hasChildren ? 'var(--accent)' : 'rgba(255,255,255,0.4)' }} />
        <span className="tree-row-name">{depth === 0 ? node.name : node.name}</span>
        <span className="tree-row-count">{node.count}</span>
        <div className="tree-row-bar">
          <div style={{ width: `${Math.min(100, (node.count / TREE.count) * 100)}%` }} />
        </div>
      </button>
      {open && hasChildren && node.children.map((c) => (
        <TreeNode key={c.name} node={c} depth={depth + 1} />
      ))}
    </>
  );
}

function Treemap() {
  // Simple slice-and-dice on top-level dirs.
  const items = TREE.children.map((c) => ({ name: c.name, value: c.count })).sort((a, b) => b.value - a.value);
  const total = items.reduce((s, x) => s + x.value, 0);
  const W = 100, H = 60;
  // Naive 2-row layout.
  let row1 = [], row2 = [], cum = 0;
  const half = total / 2;
  items.forEach((it) => {
    if (cum < half) { row1.push(it); cum += it.value; } else { row2.push(it); }
  });
  const sum = (arr) => arr.reduce((s, x) => s + x.value, 0);
  const colors = ['var(--accent)', '#60a5fa', '#a78bfa', '#fbbf24', '#f87171', '#fb923c', '#34d399', '#f472b6'];
  const renderRow = (row, y, h) => {
    const w = sum(row) || 1;
    let x = 0;
    return row.map((it, i) => {
      const ww = (it.value / w) * 100;
      const node = (
        <div key={it.name} className="tm-cell"
             style={{ left: `${x}%`, top: `${y}%`, width: `${ww}%`, height: `${h}%`,
                      background: colors[(i + (row === row2 ? 4 : 0)) % colors.length] }}>
          <div className="tm-name">/{it.name}</div>
          <div className="tm-count">{it.value}</div>
        </div>
      );
      x += ww;
      return node;
    });
  };
  return (
    <div className="card">
      <div className="card-head"><h3>Treemap by directory</h3></div>
      <div className="treemap">
        {renderRow(row1, 0, 100 * (sum(row1) / total))}
        {renderRow(row2, 100 * (sum(row1) / total), 100 - 100 * (sum(row1) / total))}
      </div>
    </div>
  );
}

// ── Exports ─────────────────────────────────────────────────────────────────
function ExportsPage() {
  const exports = [
    { name: 'all-urls.csv', desc: 'Every crawled URL with full SEO columns', size: '1.4 MB', rows: 2310 },
    { name: 'issues.xlsx', desc: 'Issues grouped by category with affected URLs', size: '412 KB', rows: 4521 },
    { name: 'sitemap.xml', desc: 'Generated sitemap from successful 200s', size: '178 KB', rows: 1956 },
    { name: 'broken-links.csv', desc: 'All 4xx and 5xx with referring pages', size: '88 KB', rows: 312 },
    { name: 'redirects.csv', desc: '3xx chains with hop counts', size: '64 KB', rows: 211 },
    { name: 'metadata.json', desc: 'Full page metadata (titles, meta, H1)', size: '2.1 MB', rows: 2310 },
  ];
  return (
    <div className="page-grid">
      <PageHeader title="Exports"
        subtitle="Download crawl data in any format — CSV, JSON, XML, XLSX."
        actions={<button className="btn primary"><Icon name="plus" size={11} /><span>New export</span></button>}
      />
      <div className="row exports-row">
        {exports.map((e) => (
          <div key={e.name} className="card export-card">
            <div className="export-icon"><Icon name="file" size={20} /></div>
            <div className="export-body">
              <div className="export-name">{e.name}</div>
              <div className="export-desc">{e.desc}</div>
              <div className="export-meta">
                <span>{e.rows.toLocaleString()} rows</span>
                <span className="text-muted">·</span>
                <span>{e.size}</span>
              </div>
            </div>
            <button className="btn ghost"><Icon name="download" size={11} /><span>Download</span></button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Settings ────────────────────────────────────────────────────────────────
function SettingsPage() {
  return (
    <div className="page-grid">
      <PageHeader title="Settings" subtitle="Configure how Lattice crawls lumen.travel." />
      <div className="row settings-row">
        <div className="card settings-card">
          <h3>Crawl configuration</h3>
          <SettingRow label="User agent" value="LatticeBot/2.4 (+https://lattice.so/bot)" />
          <SettingRow label="Crawl rate" value="55 URLs / second" hint="Recommended for medium sites" />
          <SettingRow label="Max depth" value="∞" />
          <SettingRow label="Max URLs" value="50,000" />
          <SettingRow label="Render JavaScript" value="Yes" toggle />
          <SettingRow label="Follow robots.txt" value="Yes" toggle />
          <SettingRow label="Follow nofollow" value="No" toggle off />
        </div>
        <div className="card settings-card">
          <h3>Schedule</h3>
          <SettingRow label="Frequency" value="Weekly · Mondays at 09:00 IST" />
          <SettingRow label="Notifications" value="errors@lumen.travel" />
          <SettingRow label="Slack alerts" value="#seo-alerts" />
          <SettingRow label="Threshold" value="Notify on > 50 new errors" />
        </div>
        <div className="card settings-card">
          <h3>Inclusions / exclusions</h3>
          <SettingRow label="Excluded paths" value="/account/* · /api/*" mono />
          <SettingRow label="Excluded params" value="utm_* · gclid · fbclid" mono />
          <SettingRow label="Custom user agents" value="3 configured" />
        </div>
        <div className="card settings-card">
          <h3>API & integrations</h3>
          <SettingRow label="API key" value="lat_pk_live_••••••••42c1" mono />
          <SettingRow label="Webhook" value="https://lumen.travel/api/seo-webhook" mono />
          <SettingRow label="GA4 connection" value="Connected" badge="Connected" />
        </div>
      </div>
    </div>
  );
}

function SettingRow({ label, value, hint, toggle, off, mono, badge }) {
  return (
    <div className="setting-row">
      <div>
        <div className="setting-label">{label}</div>
        {hint && <div className="setting-hint">{hint}</div>}
      </div>
      <div className="setting-value">
        {badge && <span className="status-online" style={{ marginRight: 8 }}><span className="status-dot" />{badge}</span>}
        {toggle ? (
          <button className="toggle-pill" data-on={off ? '0' : '1'}>
            <i />
          </button>
        ) : (
          <span className={mono ? 'mono' : ''}>{value}</span>
        )}
      </div>
    </div>
  );
}

// ── Page header ─────────────────────────────────────────────────────────────
function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

Object.assign(window, {
  PagesUrlsPage, IssuesPage, SessionsPage, AnalyticsPage,
  VisualizationsPage, ExportsPage, SettingsPage, PageHeader,
});
