import { useCallback, useState } from 'react';
import Icon from '../components/Icon';
import Button from '../components/Button';
import { fmtTime, type BadgeTone } from '../format';
import { useCrawlerLogs } from '../useCrawlerLogs';
import { type CrawlerLogMessage } from '../api';

const CAP = 5000;
const TYPES = ['success', 'error', 'info', 'warning', 'stopped', 'complete'] as const;
type LogType = (typeof TYPES)[number];

function tone(t: string): BadgeTone {
  if (t === 'error' || t === 'stopped') return 'err';
  if (t === 'warning') return 'warn';
  if (t === 'success' || t === 'complete') return 'ok';
  return 'info';
}

export default function CrawlerLogs() {
  const [logs, setLogs] = useState<CrawlerLogMessage[]>([]);
  const [filter, setFilter] = useState<Set<LogType>>(new Set(TYPES));
  const [q, setQ] = useState('');

  const onMessage = useCallback((m: CrawlerLogMessage) => {
    if (m.type === 'snapshot') return;
    setLogs((prev) => {
      const next = [...prev, m];
      return next.length > CAP ? next.slice(next.length - CAP) : next;
    });
  }, []);
  useCrawlerLogs(onMessage);

  const toggle = (t: LogType) => {
    setFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };
  const shown = logs.filter(
    (l) =>
      filter.has((l.type ?? 'info') as LogType) &&
      (!q || (l.message || '').toLowerCase().includes(q.toLowerCase())),
  );

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              terminal
            </span>
            Live Logs
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              stream
            </span>
            Every crawl event streamed from the crawler engine in real-time.
          </p>
        </div>
        <Button variant="ghost" icon="clear_all" onClick={() => setLogs([])}>
          Clear
        </Button>
      </div>

      <div className="controls">
        <div style={{ position: 'relative', flex: 1, maxWidth: 420 }}>
          <Icon
            name="search"
            size="16px"
            style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search messages..."
            style={{
              width: '100%',
              padding: '8px 12px 8px 32px',
              border: '1px solid var(--border)',
              borderRadius: 6,
              background: 'var(--surface-alt)',
              outline: 'none',
              fontSize: 13,
            }}
          />
        </div>
        <div className="divider" />
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => toggle(t)}
            className={`badge ${filter.has(t) ? tone(t) : 'muted'}`}
            style={{ cursor: 'pointer', padding: '4px 10px', fontSize: 11.5 }}
          >
            {t}
          </button>
        ))}
        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          {shown.length.toLocaleString()} / {logs.length.toLocaleString()}
        </div>
      </div>

      <div className="card">
        <div className="log-panel" style={{ maxHeight: 'calc(100vh - 300px)' }}>
          {shown.map((e, i) => (
            <div key={i} className={`log-row ${e.type || 'info'}`}>
              <span className="ts">{fmtTime(e.timestamp)}</span>
              <span>{e.message}</span>
            </div>
          ))}
          {shown.length === 0 && (
            <div style={{ color: 'var(--text-muted)', padding: 30, textAlign: 'center' }}>
              No logs match current filters.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
