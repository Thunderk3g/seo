import { useEffect, useState } from 'react';
import { crawlerApi, type CrawlerStatus } from './api';

// Polls /crawler-api/status every `ms` milliseconds until unmounted.
// Ported from Crawler_v2.0.0 useCrawlerStatus.js.
export function useCrawlerStatus(ms = 3000): { status: CrawlerStatus | null; error: string | null } {
  const [status, setStatus] = useState<CrawlerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await crawlerApi.status();
        if (alive) {
          setStatus(s);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    };
    tick();
    const id = setInterval(tick, ms);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [ms]);

  return { status, error };
}
