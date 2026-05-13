import Badge from './Badge';
import Icon from './Icon';
import { statusBadge } from '../format';
import type { CrawlerLogMessage } from '../api';

export default function RecentPagesTable({ rows }: { rows: CrawlerLogMessage[] }) {
  return (
    <div className="card" style={{ height: '100%' }}>
      <div className="card-head">
        <Icon name="history" /> Recent Pages
        <span className="pill">{rows.length}</span>
      </div>
      <div className="tbl-wrap" style={{ borderRadius: 0, maxHeight: 520 }}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 56 }}>#</th>
              <th style={{ width: 80 }}>Status</th>
              <th>URL</th>
              <th style={{ width: 60 }}>Depth</th>
              <th style={{ width: 80, textAlign: 'right' }}>ms</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const msg = r.message || '';
              const m = msg.match(/\[(\d+)\]/);
              const ms = msg.match(/(\d+)ms/);
              const code = m ? m[1] : '?';
              return (
                <tr key={i}>
                  <td>{r.crawled ?? ''}</td>
                  <td>
                    <Badge tone={statusBadge(code)}>{code}</Badge>
                  </td>
                  <td className="url" title={r.url}>
                    {r.url}
                  </td>
                  <td className="center">{r.depth ?? ''}</td>
                  <td className="num">{ms ? ms[1] : ''}</td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 28 }}>
                  No pages crawled yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
