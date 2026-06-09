import { useEffect, useState } from 'react';
import Icon from './Icon';
import { crawlerApi, type CrawlHistoryResponse, type CrawlHistoryRow } from '../api';

const KIND_LABEL: Record<CrawlHistoryRow['kind'], string> = {
  bajaj: 'Crawler engine (own site)',
  content: 'Content crawl (own site)',
  competitor: 'Competitor',
  adhoc: 'Ad-hoc URL',
};

const STATUS_COLOR: Record<CrawlHistoryRow['status'], string> = {
  running: '#0072ce',
  complete: '#16a34a',
  failed: '#b91c1b',
  stopped: '#b45309',
};

function fmtDuration(sec: number | null): string {
  if (sec === null || sec < 0) return '—';
  if (sec < 90) return `${sec}s`;
  const m = Math.round(sec / 60);
  return m < 90 ? `${m}m` : `${(m / 60).toFixed(1)}h`;
}

/**
 * Crawl history — every crawl the system has run (engine / content /
 * competitor / ad-hoc), newest first. Running crawls show their LIVE
 * page count (rows persist as they arrive, so reports populate during
 * the crawl); stopped/failed runs show how far they got (%).
 * Polls every 15 s while anything is running.
 */
export default function CrawlHistoryPanel() {
  const [data, setData] = useState<CrawlHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const load = () => {
      crawlerApi
        .history()
        .then((d) => {
          if (!alive) return;
          setData(d);
          setError(null);
          timer = window.setTimeout(load, d.any_running ? 15_000 : 60_000);
        })
        .catch((e) => {
          if (!alive) return;
          setError(e instanceof Error ? e.message : String(e));
          timer = window.setTimeout(load, 60_000);
        });
    };
    load();
    return () => {
      alive = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  if (error) {
    return (
      <div className="card" style={{ padding: 14, marginTop: 14, color: 'var(--red)' }}>
        <Icon name="error" /> Crawl history unavailable: {error}
      </div>
    );
  }
  if (!data) return null;

  return (
    <section className="card" style={{ padding: 16, marginTop: 14 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 17, display: 'flex', alignItems: 'center', gap: 6 }}>
        <Icon name="history" /> Crawl history
        {data.any_running && (
          <span style={{ fontSize: 11.5, fontWeight: 700, color: '#0072ce' }}>
            ● live — pages populate reports while the crawl runs
          </span>
        )}
      </h2>
      <div style={{ fontSize: 12.5, color: '#475569', marginBottom: 10 }}>
        All crawls — crawler engine, own-site content, competitors and ad-hoc — newest first.
        Stopped runs keep whatever was crawled; the % shows how far they got.
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#475569', borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ padding: '6px 8px' }}>Started</th>
              <th style={{ padding: '6px 8px' }}>Type</th>
              <th style={{ padding: '6px 8px' }}>Domain</th>
              <th style={{ padding: '6px 8px' }}>Status</th>
              <th style={{ padding: '6px 8px', textAlign: 'right' }}>Pages (live)</th>
              <th style={{ padding: '6px 8px', textAlign: 'right' }}>OK</th>
              <th style={{ padding: '6px 8px', textAlign: 'right' }}>% done</th>
              <th style={{ padding: '6px 8px', textAlign: 'right' }}>Duration</th>
            </tr>
          </thead>
          <tbody>
            {data.crawls.map((c) => (
              <tr key={c.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>
                  {c.started_at ? new Date(c.started_at).toLocaleString() : '—'}
                </td>
                <td style={{ padding: '6px 8px' }}>{KIND_LABEL[c.kind] ?? c.kind}</td>
                <td style={{ padding: '6px 8px' }}>
                  <code style={{ fontSize: 12 }}>{c.target_domain || '—'}</code>
                </td>
                <td style={{ padding: '6px 8px', fontWeight: 700, color: STATUS_COLOR[c.status] ?? '#334155' }}>
                  {c.status}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{c.pages_in_db.toLocaleString()}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{c.pages_ok.toLocaleString()}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                  {c.completion_pct !== null ? `${c.completion_pct}%` : '—'}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmtDuration(c.duration_sec)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
