import { useMemo, useState } from 'react';
import Badge from './Badge';
import Icon from './Icon';
import { statusBadge } from '../format';

// Colour-aware paginated table (renders current page only).
// Ported from Crawler_v2.0.0 reports/DataTable.jsx.
export default function DataTable({
  headers,
  rows,
  pageSize = 100,
}: {
  headers: string[];
  rows: string[][];
  pageSize?: number;
}) {
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    if (!q) return rows;
    const needle = q.toLowerCase();
    return rows.filter((r) => r.some((c) => String(c).toLowerCase().includes(needle)));
  }, [rows, q]);

  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const start = page * pageSize;
  const slice = filtered.slice(start, start + pageSize);

  const statusIdx = headers.indexOf('status');
  const codeIdx = headers.indexOf('status_code');
  const urlIdx = headers.indexOf('url');

  return (
    <div className="card">
      <div className="card-head">
        <Icon name="table_view" /> Table
        <span className="pill">{total.toLocaleString()} rows</span>
        <div style={{ marginLeft: 12, flex: 1, maxWidth: 360 }}>
          <div style={{ position: 'relative' }}>
            <Icon
              name="search"
              size="16px"
              style={{
                position: 'absolute',
                left: 10,
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)',
              }}
            />
            <input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(0);
              }}
              placeholder="Filter..."
              style={{
                width: '100%',
                padding: '7px 12px 7px 32px',
                border: '1px solid var(--border)',
                borderRadius: 6,
                background: 'var(--surface-alt)',
                fontSize: 13,
                fontFamily: 'inherit',
                outline: 'none',
              }}
            />
          </div>
        </div>
      </div>
      <div className="tbl-wrap" style={{ borderRadius: 0 }}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 48 }}>#</th>
              {headers.map((h) => (
                <th key={h}>{h.replace(/_/g, ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((r, i) => (
              <tr key={start + i}>
                <td style={{ color: 'var(--text-muted)' }}>{start + i + 1}</td>
                {r.map((v, j) => {
                  if (j === statusIdx) {
                    const tone = v === 'OK' ? 'ok' : v ? 'err' : 'muted';
                    return (
                      <td key={j}>
                        <Badge tone={tone}>{v || '—'}</Badge>
                      </td>
                    );
                  }
                  if (j === codeIdx) {
                    return (
                      <td key={j}>
                        <Badge tone={statusBadge(v)}>{v || '—'}</Badge>
                      </td>
                    );
                  }
                  if (j === urlIdx)
                    return (
                      <td key={j} className="url" title={v}>
                        {v}
                      </td>
                    );
                  return (
                    <td key={j} title={String(v)}>
                      {v}
                    </td>
                  );
                })}
              </tr>
            ))}
            {slice.length === 0 && (
              <tr>
                <td
                  colSpan={headers.length + 1}
                  style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}
                >
                  No rows match filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '10px 16px',
          gap: 12,
          borderTop: '1px solid var(--border)',
          background: 'var(--surface-alt)',
        }}
      >
        <button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
          <Icon name="chevron_left" /> Prev
        </button>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          Page <b>{page + 1}</b> of <b>{pages}</b>
        </div>
        <button
          className="btn btn-ghost"
          disabled={page + 1 >= pages}
          onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
        >
          Next <Icon name="chevron_right" />
        </button>
        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          Showing {slice.length} of {total.toLocaleString()}
        </div>
      </div>
    </div>
  );
}
