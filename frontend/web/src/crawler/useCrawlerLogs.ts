import { useEffect, useRef } from 'react';
import { crawlerApi, type CrawlerLogMessage } from './api';

// Drop-in replacement for the old useWebSocket hook used against /ws/logs.
// Polls /api/v1/crawler/logs every `ms` milliseconds and replays each new
// message through `onMessage`, preserving the per-frame callback pattern
// the dashboard already relies on (snapshot suppression, recent table,
// live stat extraction).
//
// On the very first tick we synthesize a `{ type: 'snapshot', ...}`
// message from the response's top-level `is_running` + `stats` so existing
// snapshot-handling code paths (e.g. seeding `startedAt` from stats) keep
// working without changes.
export function useCrawlerLogs(
  onMessage: (msg: CrawlerLogMessage) => void,
  ms = 1000,
): void {
  const cbRef = useRef(onMessage);
  cbRef.current = onMessage;

  useEffect(() => {
    let alive = true;
    let cursor: number | null = null;
    let firstTick = true;

    const tick = async () => {
      try {
        const r = await crawlerApi.logs(cursor);
        if (!alive) return;
        cursor = r.cursor;
        if (firstTick) {
          firstTick = false;
          cbRef.current({
            type: 'snapshot',
            is_running: r.is_running,
            stats: r.stats,
          });
        }
        for (const m of r.messages) {
          if (!alive) return;
          cbRef.current(m);
        }
      } catch {
        /* swallow transient errors; next tick retries */
      }
    };

    tick();
    const id = setInterval(tick, ms);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [ms]);
}
