// QuickStats.tsx — sidebar inset showing live KPIs for the most recent
// session of the active site. Mirrors `.design-ref/project/shell.jsx`'s
// quick-stats block (lines 66–79), wired to the real `useOverview` payload.
//
// Data flow:
//   activeSiteId → useSessions(activeSiteId) → latestSessionId
//   → useOverview(latestSessionId) → kpis + system_metrics
//
// Rows whose source value is unavailable (null / missing) are omitted —
// per the audit, we never invent values just to fill the panel. The
// "Crawl rate" row from the design ref is skipped entirely because the
// backend overview payload doesn't expose a per-second rate.

import { useEffect, useState } from 'react';
import { useOverview } from '../api/hooks/useOverview';

interface QuickStatsProps {
  sessionId: string | null;
}

function formatElapsed(totalSec: number): string {
  if (!Number.isFinite(totalSec) || totalSec < 0) totalSec = 0;
  // Cap at 99:59:59 so the layout never widens unexpectedly.
  const capped = Math.min(totalSec, 99 * 3600 + 59 * 60 + 59);
  const h = Math.floor(capped / 3600);
  const m = Math.floor((capped % 3600) / 60);
  const s = Math.floor(capped % 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

export default function QuickStats({ sessionId }: QuickStatsProps) {
  const overview = useOverview(sessionId);

  // Live elapsed: tick once per second while the session is running so the
  // sidebar stays in lockstep with the topbar progress sub-row.
  const [now, setNow] = useState(() => Date.now());
  const isRunning = overview.data?.session_status === 'running';
  useEffect(() => {
    if (!isRunning) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isRunning]);

  if (!sessionId || !overview.data) return null;

  const { kpis, system_metrics, started_at, duration_seconds } = overview.data;

  // Elapsed: live tick while running, frozen `duration_seconds` once terminal.
  let elapsed: string | null = null;
  if (isRunning && started_at) {
    const startMs = new Date(started_at).getTime();
    if (Number.isFinite(startMs)) {
      elapsed = formatElapsed((now - startMs) / 1000);
    }
  } else if (duration_seconds !== null && duration_seconds !== undefined) {
    elapsed = formatElapsed(duration_seconds);
  }

  const rows: Array<{ label: string; value: string; cls?: string }> = [];
  rows.push({
    label: 'Total URLs',
    value: kpis.total_urls.toLocaleString(),
  });
  rows.push({ label: 'Crawled', value: kpis.crawled.toLocaleString() });
  rows.push({ label: 'Pending', value: kpis.pending.toLocaleString() });
  rows.push({
    label: 'Errors',
    value: kpis.failed.toLocaleString(),
    cls: 'qs-err',
  });
  if (system_metrics.avg_response_time_ms != null) {
    rows.push({
      label: 'Avg. response',
      value: `${Math.round(system_metrics.avg_response_time_ms)} ms`,
    });
  }
  if (elapsed) {
    rows.push({ label: 'Elapsed', value: elapsed });
  }

  return (
    <div className="sidebar-section">
      <div className="sidebar-section-title">Quick stats</div>
      <div className="quick-stats">
        {rows.map((r) => (
          <div className="qs-row" key={r.label}>
            <span>{r.label}</span>
            <b className={r.cls} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {r.value}
            </b>
          </div>
        ))}
      </div>
    </div>
  );
}
