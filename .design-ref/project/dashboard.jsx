// dashboard.jsx — main dashboard page composed of cards.

function StatCard({ label, value, color, sub, sparkData, sparkColor, dim }) {
  return (
    <div className="card stat-card">
      <div className="stat-head">
        <div className="stat-dot" style={{ background: color }} />
        <span className="stat-label">{label}</span>
      </div>
      <div className="stat-value-row">
        <div className="stat-value">{typeof value === 'number' ? value.toLocaleString() : value}</div>
        <Sparkline data={sparkData} width={110} height={36}
                   color={sparkColor || color} fill={true} />
      </div>
      <div className={'stat-sub ' + (dim ? 'dim' : '')}>{sub}</div>
    </div>
  );
}

function SeoHealthCard({ score = 78 }) {
  const subs = [
    { name: 'Technical SEO', value: 82, color: 'var(--accent)' },
    { name: 'Content SEO',   value: 75, color: '#fbbf24' },
    { name: 'Performance',   value: 76, color: '#60a5fa' },
  ];
  return (
    <div className="card health-card">
      <div className="card-head">
        <h3>SEO Health Score</h3>
        <button className="link-btn">View report <Icon name="chevRight" size={11} /></button>
      </div>
      <div className="health-body">
        <div className="health-gauge">
          <Gauge value={score} size={140} thickness={10} color="var(--accent)" />
          <div className="health-gauge-text">
            <div className="health-score">{score}</div>
            <div className="health-score-sub">/ 100</div>
            <div className="health-score-label">Good</div>
          </div>
        </div>
        <div className="health-subs">
          {subs.map((s) => (
            <div key={s.name} className="health-sub">
              <div className="health-sub-row">
                <span>{s.name}</span>
                <b>{s.value}<span className="text-muted">/100</span></b>
              </div>
              <Meter value={s.value} color={s.color} height={5} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function IssueDistributionCard() {
  const errors = ISSUES.filter((i) => i.severity === 'error').reduce((s, i) => s + i.count, 0);
  const warnings = ISSUES.filter((i) => i.severity === 'warning').reduce((s, i) => s + i.count, 0);
  const notices = ISSUES.filter((i) => i.severity === 'notice').reduce((s, i) => s + i.count, 0);
  const total = errors + warnings + notices;
  const segs = [
    { value: errors,   color: '#f87171', label: 'Errors' },
    { value: warnings, color: '#fbbf24', label: 'Warnings' },
    { value: notices,  color: '#60a5fa', label: 'Notices' },
  ];
  return (
    <div className="card">
      <div className="card-head">
        <h3>Issue distribution</h3>
        <button className="link-btn">View all <Icon name="chevRight" size={11} /></button>
      </div>
      <div className="issue-dist-body">
        <Donut segments={segs} size={140} thickness={14}
               label={total.toLocaleString()} sublabel="Total issues" />
        <div className="issue-dist-list">
          {segs.map((s) => (
            <div key={s.label} className="issue-dist-row">
              <span className="dot-sm" style={{ background: s.color }} />
              <span className="issue-dist-label">{s.label}</span>
              <span className="issue-dist-count">{s.value.toLocaleString()}</span>
              <span className="issue-dist-pct">{((s.value / total) * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CrawlOverviewCard({ crawl }) {
  const rows = [
    ['Started', '2026-05-06 13:30 IST'],
    ['Duration', crawl.elapsed],
    ['Avg. response', Math.round(crawl.avgMs) + ' ms'],
    ['URLs / second', crawl.rate.toFixed(1)],
    ['Depth reached', '6'],
    ['User agent', 'LatticeBot/2.4'],
    ['JavaScript', <span style={{ color: 'var(--accent)' }}>Rendered</span>],
    ['robots.txt', <span style={{ color: 'var(--accent)' }}>Followed</span>],
  ];
  return (
    <div className="card">
      <div className="card-head">
        <h3>Crawl overview</h3>
        <span className="muted-pill">Session #2641</span>
      </div>
      <div className="overview-list">
        {rows.map(([k, v]) => (
          <div key={k} className="overview-row">
            <span>{k}</span>
            <b>{v}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityFeed({ items }) {
  return (
    <div className="card activity-card">
      <div className="card-head">
        <h3>Crawl activity</h3>
        <button className="link-btn">View all <Icon name="chevRight" size={11} /></button>
      </div>
      <div className="activity-list">
        {items.map((it) => (
          <div key={it.id} className={'activity-row ' + it.kind}>
            <span className="activity-time">{it.time}</span>
            <span className="activity-marker" />
            <div className="activity-body">
              <div className="activity-verb">{it.verb}
                {it.status && <span className={'status-pill s' + Math.floor(it.status / 100)}>{it.status}</span>}
              </div>
              <div className="activity-url">{it.url}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TopIssuesCard({ onSelect }) {
  const top = ISSUES.slice().sort((a, b) => b.count - a.count).slice(0, 8);
  return (
    <div className="card">
      <div className="card-head">
        <h3>Top issues</h3>
        <button className="link-btn">View all <Icon name="chevRight" size={11} /></button>
      </div>
      <div className="top-issues">
        {top.map((i) => (
          <button key={i.id} className="top-issue-row" onClick={() => onSelect(i)}>
            <span className={'sev-dot sev-' + i.severity} />
            <span className="top-issue-name">{i.name}</span>
            <span className="top-issue-count">{i.count.toLocaleString()}</span>
            <Icon name="chevRight" size={11} />
          </button>
        ))}
      </div>
    </div>
  );
}

function SystemMetrics({ metrics }) {
  return (
    <div className="card sysmet-card">
      <div className="card-head">
        <h3>System</h3>
        <span className="status-online"><span className="status-dot" /> Healthy</span>
      </div>
      <div className="sysmet-grid">
        <div className="sysmet-item">
          <div className="sysmet-label">Requests / sec</div>
          <div className="sysmet-value">{metrics.rps.toFixed(1)}</div>
          <LiveArea data={metrics.rpsHistory} width={170} height={32} color="var(--accent)" />
        </div>
        <div className="sysmet-item">
          <div className="sysmet-label">Queue size</div>
          <div className="sysmet-value">{metrics.queue.toLocaleString()}</div>
          <LiveArea data={metrics.queueHistory} width={170} height={32} color="#60a5fa" />
        </div>
        <div className="sysmet-item">
          <div className="sysmet-label">Threads active</div>
          <div className="sysmet-value">{metrics.threads} <span className="sysmet-of">/ 32</span></div>
          <Meter value={metrics.threads} max={32} color="#a78bfa" height={4} />
        </div>
        <div className="sysmet-item">
          <div className="sysmet-label">Memory</div>
          <div className="sysmet-value">{metrics.memMb} <span className="sysmet-of">MB</span></div>
          <Meter value={metrics.memMb} max={2048} color="#fbbf24" height={4} />
        </div>
      </div>
    </div>
  );
}

function DashboardPage({ crawl, activity, metrics, onIssueSelect, onNav }) {
  return (
    <div className="page-grid">
      <div className="row stat-row">
        <StatCard label="Total URLs" value={crawl.total} color="#a78bfa"
                  sparkData={sparkline(31, 24, 50, 12, 0.6)}
                  sub={<><Icon name="arrowUp" size={10} /> 18.7% vs last crawl</>} />
        <StatCard label="Crawled" value={crawl.crawled} color="var(--accent)"
                  sparkData={sparkline(7, 24, 60, 22, 1.2)}
                  sub={<>{((crawl.crawled / crawl.total) * 100).toFixed(1)}% of total</>} />
        <StatCard label="Pending" value={crawl.pending} color="#fbbf24"
                  sparkData={sparkline(13, 24, 50, 30)}
                  sub={<>{((crawl.pending / crawl.total) * 100).toFixed(1)}% of total</>} dim />
        <StatCard label="Failed" value={crawl.failed} color="#f87171"
                  sparkData={sparkline(2, 24, 30, 22)}
                  sub={<>{((crawl.failed / crawl.crawled) * 100 || 0).toFixed(2)}% error rate</>} />
        <StatCard label="Excluded" value={crawl.excluded} color="#60a5fa"
                  sparkData={sparkline(5, 24, 40, 18)}
                  sub={<>by robots.txt &amp; rules</>} dim />
      </div>

      <div className="row dash-row-2">
        <SeoHealthCard score={crawl.healthScore} />
        <IssueDistributionCard />
        <CrawlOverviewCard crawl={crawl} />
      </div>

      <div className="row dash-row-3">
        <UrlMiniTable onNav={onNav} />
        <ActivityFeed items={activity} />
      </div>

      <div className="row dash-row-4">
        <SystemMetrics metrics={metrics} />
        <TopIssuesCard onSelect={onIssueSelect} />
        <SiteStructureMini />
      </div>
    </div>
  );
}

// Compact URL preview for the dashboard.
function UrlMiniTable({ onNav }) {
  const rows = URLS.slice(0, 8);
  const [tab, setTab] = React.useState('all');
  const tabs = [
    { id: 'all', label: 'All', count: URLS.length },
    { id: 'html', label: 'HTML', count: URLS.filter((u) => u.contentType === 'html').length },
    { id: 'images', label: 'Images', count: URLS.filter((u) => u.contentType === 'image').length },
    { id: 'errors', label: 'Errors', count: URLS.filter((u) => u.status >= 400).length },
  ];
  const filtered = tab === 'all' ? rows :
    tab === 'errors' ? URLS.filter((u) => u.status >= 400).slice(0, 8) :
    URLS.filter((u) => u.contentType === (tab === 'html' ? 'html' : 'image')).slice(0, 8);
  return (
    <div className="card url-mini">
      <div className="card-head">
        <div className="tabs">
          {tabs.map((t) => (
            <button key={t.id} className={'tab ' + (t.id === tab ? 'active' : '')}
                    onClick={() => setTab(t.id)}>
              {t.label} <span className="tab-count">{t.count.toLocaleString()}</span>
            </button>
          ))}
        </div>
        <button className="link-btn" onClick={() => onNav('pages')}>
          Open table <Icon name="external" size={11} />
        </button>
      </div>
      <div className="url-table">
        <div className="url-table-head">
          <div>URL</div>
          <div>Status</div>
          <div>Title</div>
          <div className="num">Resp</div>
          <div className="num">Size</div>
        </div>
        {filtered.slice(0, 8).map((u) => (
          <div key={u.id} className="url-row">
            <div className="url-cell" title={u.url}>{u.path}</div>
            <div><span className={'status-pill s' + Math.floor(u.status / 100)}>{u.status}</span></div>
            <div className="title-cell" title={u.title}>{u.title || <span className="text-muted-i">— missing —</span>}</div>
            <div className="num">{Math.round(u.responseTime)}<span className="text-muted">ms</span></div>
            <div className="num">{u.size.toFixed(1)}<span className="text-muted">KB</span></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SiteStructureMini() {
  return (
    <div className="card">
      <div className="card-head">
        <h3>Site structure</h3>
        <button className="link-btn">View tree <Icon name="chevRight" size={11} /></button>
      </div>
      <div className="tree-mini">
        {TREE.children.slice(0, 6).map((n) => (
          <div key={n.name} className="tree-mini-row">
            <Icon name="folder" size={13} />
            <span className="tree-mini-name">/{n.name}</span>
            <span className="tree-mini-count">{n.count}</span>
            <div className="tree-mini-bar">
              <div style={{ width: `${Math.min(100, (n.count / 200) * 100)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { DashboardPage });
