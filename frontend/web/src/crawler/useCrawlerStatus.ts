import { useEffect, useState } from 'react';
import { crawlerApi, type CrawlerStatus } from './api';

// Polls /crawler-api/status every `ms` milliseconds until unmounted.
//
// Uses a self-scheduling setTimeout loop (NOT setInterval): the next
// request is scheduled only AFTER the current one settles. setInterval
// fires on a fixed clock regardless of in-flight requests, so when the
// backend lags (e.g. busy with a crawl) requests pile up unboundedly
// until the browser throws ERR_INSUFFICIENT_RESOURCES. This pattern
// self-throttles to "one request at a time" and backs off on error.
export function useCrawlerStatus(ms = 3000): { status: CrawlerStatus | null; error: string | null } {
  const [status, setStatus] = useState<CrawlerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      let delay = ms;
      try {
        const s = await crawlerApi.status();
        if (alive) {
          setStatus(s);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
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

  return { status, error };
}
