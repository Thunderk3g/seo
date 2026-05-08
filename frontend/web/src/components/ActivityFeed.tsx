// ActivityFeed.tsx — live crawl activity panel for the Dashboard.
//
// Lifts `.activity-card` / `.activity-row` styles from lattice.css. The
// design's `kind` taxonomy (crawl/ok/meta/links/image/redirect/404) is mapped
// from our backend's CrawlEventKind so the dot colors match the design.
//
// Polling lives in `useActivity` (1.5s while running). This component only
// renders the most recent N rows from a rolling buffer.

import type { CrawlEvent, CrawlEventKind } from '../api/types';

interface ActivityFeedProps {
  events: CrawlEvent[] | undefined;
  isLoading: boolean;
  isLive: boolean;
  maxRows?: number;
}

const KIND_TO_DESIGN_CLASS: Record<CrawlEventKind, string> = {
  crawl: 'crawl',
  discovery: 'links',
  skip: 'meta',
  error: '404',
  blocked: '404',
  redirect: 'redirect',
  session: 'ok',
};

const KIND_TO_VERB: Record<CrawlEventKind, string> = {
  crawl: 'Crawled',
  discovery: 'Discovered',
  skip: 'Skipped',
  error: 'Error',
  blocked: 'Blocked',
  redirect: 'Redirect',
  session: 'Session',
};

function statusPillClass(code: unknown): string | null {
  if (typeof code !== 'number' || code <= 0) return null;
  return `status-pill s${Math.floor(code / 100)}`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export default function ActivityFeed({
  events,
  isLoading,
  isLive,
  maxRows = 14,
}: ActivityFeedProps) {
  const rows = (events ?? []).slice(0, maxRows);

  return (
    <div className="card activity-card" style={{ padding: 'var(--pad)' }}>
      <div className="card-head">
        <h3>
          Crawl activity
          {isLive && (
            <span
              className="state-dot"
              style={{ marginLeft: 8, background: 'var(--accent)' }}
              aria-label="Live"
            />
          )}
        </h3>
      </div>

      {isLoading && rows.length === 0 && (
        <p className="text-muted" style={{ padding: '12px 4px' }}>Waiting for activity…</p>
      )}

      {!isLoading && rows.length === 0 && (
        <p className="text-muted" style={{ padding: '12px 4px' }}>
          {isLive
            ? 'Crawl in progress — events will appear here as URLs are processed.'
            : 'No activity yet. Events appear here once a crawl runs.'}
        </p>
      )}

      <div className="activity-list">
        {rows.map((it) => {
          const designClass = KIND_TO_DESIGN_CLASS[it.kind] ?? 'ok';
          const status = (it.metadata as { status_code?: number } | null)?.status_code;
          const pill = statusPillClass(status);
          return (
            <div key={it.id} className={'activity-row ' + designClass}>
              <span className="activity-time">{formatTime(it.timestamp)}</span>
              <span className="activity-marker" />
              <div className="activity-body">
                <div className="activity-verb">
                  {KIND_TO_VERB[it.kind] ?? it.kind}
                  {pill && status != null && (
                    <span className={pill} style={{ marginLeft: 6 }}>{status}</span>
                  )}
                </div>
                <div className="activity-url" title={it.url || it.message}>
                  {it.url || it.message}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
