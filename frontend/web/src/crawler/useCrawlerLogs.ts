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
  ms = 1500,
): void {
  const cbRef = useRef(onMessage);
  cbRef.current = onMessage;

  useEffect(() => {
    let alive = true;
    let cursor: number | null = null;
    let firstTick = true;
    let timer: ReturnType<typeof setTimeout>;

    // Self-scheduling setTimeout loop (NOT setInterval): the next poll is
    // queued only AFTER the current one settles. setInterval fires on a
    // fixed clock even while a request is still in flight, so a backend
    // that lags behind the 1s tick (e.g. busy crawling) accumulates
    // unbounded pending requests until the browser dies with
    // ERR_INSUFFICIENT_RESOURCES. This caps concurrency at one request.
    const tick = async () => {
      let delay = ms;
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
        delay = ms * 3; // back off when the backend is unreachable/slow
      } finally {
        if (alive) timer = setTimeout(tick, delay);
      }
    };

    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [ms]);
}
