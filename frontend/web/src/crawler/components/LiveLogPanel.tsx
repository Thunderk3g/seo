import { useEffect, useRef } from 'react';
import Icon from './Icon';
import { fmtTime } from '../format';
import type { CrawlerLogMessage } from '../api';

export default function LiveLogPanel({ entries }: { entries: CrawlerLogMessage[] }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [entries]);

  return (
    <div className="card" style={{ height: '100%' }}>
      <div className="card-head">
        <Icon name="terminal" /> Live Log
        <span className="pill">{entries.length} entries</span>
      </div>
      <div className="log-panel" ref={ref}>
        {entries.map((e, i) => (
          <div key={i} className={`log-row ${e.type || 'info'}`}>
            <span className="ts">{fmtTime(e.timestamp)}</span>
            <span>{e.message || JSON.stringify(e)}</span>
          </div>
        ))}
        {entries.length === 0 && (
          <div style={{ color: 'var(--text-muted)', padding: 20, textAlign: 'center' }}>
            No live logs yet. Start a crawl to see telemetry here.
          </div>
        )}
      </div>
    </div>
  );
}
