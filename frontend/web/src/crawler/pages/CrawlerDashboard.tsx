import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ControlBar from '../components/ControlBar';
import LiveLogPanel from '../components/LiveLogPanel';
import RecentPagesTable from '../components/RecentPagesTable';
import StatCard from '../components/StatCard';
import { crawlerApi, type CrawlerLogMessage, type CrawlerSummary } from '../api';
import { useCrawlerStatus } from '../useCrawlerStatus';
import { useCrawlerLogs } from '../useCrawlerLogs';

const LOG_CAP = 1200;
const RECENT_CAP = 200;

interface LiveStats {
  crawled?: number;
  discovered?: number;
  queue_size?: number;
  ok?: number;
  errors?: number;
}

export default function CrawlerDashboard() {
  const { status } = useCrawlerStatus(2500);
  const [logs, setLogs] = useState<CrawlerLogMessage[]>([]);
  const [recent, setRecent] = useState<CrawlerLogMessage[]>([]);
  const [summary, setSummary] = useState<CrawlerSummary | null>(null);
  const [liveStats, setLiveStats] = useState<LiveStats | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    crawlerApi
      .summary()
      .then(setSummary)
      .catch(() => {});
  }, [status?.is_running]);

  const onMessage = useCallback((m: CrawlerLogMessage) => {
    if (m.type === 'snapshot') {
      if (m.stats?.started_at) startedAt.current = m.stats.started_at * 1000;
      return;
    }
    setLogs((prev) => {
      const next = [...prev, m];
      return next.length > LOG_CAP ? next.slice(next.length - LOG_CAP) : next;
    });
    if (m.type === 'success' || m.type === 'error') {
      setRecent((prev) => {
        const next = [m, ...prev];
        return next.length > RECENT_CAP ? next.slice(0, RECENT_CAP) : next;
      });
    }
    setLiveStats((prev) => ({
      ...(prev || {}),
      crawled: m.crawled ?? prev?.crawled,
      discovered: m.discovered ?? prev?.discovered,
      queue_size: m.queue_size ?? prev?.queue_size,
      ok: m.ok ?? prev?.ok,
      errors: m.errors ?? prev?.errors,
    }));
    if (m.stats?.started_at) startedAt.current = m.stats.started_at * 1000;
  }, []);

  useCrawlerLogs(onMessage);

  useEffect(() => {
    if (!status?.is_running) return;
    const id = setInterval(() => {
      if (startedAt.current) setElapsed((Date.now() - startedAt.current) / 1000);
    }, 1000);
    return () => clearInterval(id);
  }, [status?.is_running]);

  const display = useMemo(
    () => ({
      crawled: liveStats?.crawled ?? status?.stats?.crawled ?? summary?.pages_crawled ?? 0,
      discovered: liveStats?.discovered ?? status?.stats?.discovered ?? summary?.discovered_edges ?? 0,
      queue: liveStats?.queue_size ?? status?.stats?.queue_size ?? 0,
      ok: liveStats?.ok ?? status?.stats?.ok ?? summary?.ok_pages ?? 0,
      errors: liveStats?.errors ?? status?.stats?.errors ?? summary?.total_errors ?? 0,
      workers: status?.stats?.active_workers ?? 0,
    }),
    [liveStats, status, summary],
  );

  const rate = useMemo(() => {
    if (!elapsed) return 0;
    return Math.round((display.crawled * 60) / elapsed);
  }, [elapsed, display.crawled]);

  const doStart = async () => {
    setLogs([]);
    setRecent([]);
    startedAt.current = Date.now();
    setElapsed(0);
    try {
      await crawlerApi.start();
    } catch (e) {
      setLogs([
        {
          type: 'error',
          message: `Start failed: ${e instanceof Error ? e.message : String(e)}`,
          timestamp: new Date().toISOString(),
        },
      ]);
    }
  };
  const doStop = async () => {
    try {
      await crawlerApi.stop();
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              speed
            </span>
            Crawler Dashboard
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              language
            </span>
            Real-time crawl telemetry for <span className="mono">&nbsp;{status?.seed || 'the configured seed'}</span>
          </p>
        </div>
        <a className="btn btn-accent" href={crawlerApi.xlsxUrl()}>
          <span className="material-icons-outlined">download</span>
          Download Excel Report
        </a>
      </div>

      <ControlBar
        running={!!status?.is_running}
        elapsed={elapsed}
        rate={rate}
        onStart={doStart}
        onStop={doStop}
        onClear={() => {
          setLogs([]);
          setRecent([]);
        }}
      />

      <div className="stats-grid">
        <StatCard tone="primary" icon="download_done" label="Crawled" value={display.crawled} />
        <StatCard tone="blue" icon="travel_explore" label="Discovered" value={display.discovered} />
        <StatCard tone="accent" icon="hourglass_top" label="Queue" value={display.queue} />
        <StatCard tone="green" icon="check_circle" label="OK (200)" value={display.ok} />
        <StatCard tone="red" icon="error" label="Errors" value={display.errors} />
        <StatCard tone="muted" icon="group_work" label="Workers" value={display.workers} />
      </div>

      <div className="grid-2">
        <LiveLogPanel entries={logs} />
        <RecentPagesTable rows={recent} />
      </div>
    </div>
  );
}
