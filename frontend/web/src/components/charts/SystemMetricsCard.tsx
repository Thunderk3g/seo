// SystemMetricsCard — Dashboard card for live system signals.
//
// Spec §4.2 / §5.4.1. Shows host CPU/memory + thread count on the left;
// Redis queue depth + Celery worker activity on the right; a captured-at
// footer underneath. Polls every 5s via useSystemMetrics().
//
// This is the *real* System Metrics card. The previous Dashboard "System
// Metrics" tile actually surfaced crawl-perf metrics (avg/p95 response
// time, depth) — those continue to live on the SEO Health card via
// OverviewService.system_metrics. This component is a separate render
// wired to /api/v1/system/metrics/.
//
// Uses inline styles + the existing .card / CSS-var palette to stay
// consistent with HealthGauge / MiniBars / IssuesPage. No new deps.

import { useSystemMetrics } from '../../api/hooks/useSystemMetrics';
import type { SystemHostMetrics } from '../../api/types';

const BAR_TRACK = 'rgba(255,255,255,0.06)';

function pickBarColor(percent: number): string {
  if (percent >= 90) return '#f87171';   // poor
  if (percent >= 70) return '#fbbf24';   // warn
  return '#6ee7b7';                      // good
}

function MiniMeter({ percent, label }: { percent: number; label: string }) {
  const safe = Math.max(0, Math.min(100, percent));
  const color = pickBarColor(safe);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 11,
          color: 'var(--text-3)',
        }}
      >
        <span>{label}</span>
        <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-1)' }}>
          {safe.toFixed(1)}%
        </span>
      </div>
      <div
        style={{
          width: '100%',
          height: 6,
          background: BAR_TRACK,
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${safe}%`,
            height: '100%',
            background: color,
            transition: 'width 200ms ease',
          }}
        />
      </div>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        fontSize: 12,
      }}
    >
      <span style={{ color: 'var(--text-3)' }}>{label}</span>
      <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-1)' }}>
        {value}
      </span>
    </div>
  );
}

function ConnectedDot({ ok }: { ok: boolean }) {
  return (
    <span
      title={ok ? 'Connected' : 'Disconnected'}
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: ok ? '#6ee7b7' : '#f87171',
        marginRight: 6,
        boxShadow: ok ? '0 0 6px rgba(110,231,183,0.6)' : 'none',
      }}
    />
  );
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

function CardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="card" style={{ padding: 'var(--pad)' }}>
      <div className="card-head" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>System metrics</h3>
        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
          Host CPU/memory, Redis queue, Celery workers
        </div>
      </div>
      {children}
    </div>
  );
}

function Body({ data }: { data: SystemHostMetrics }) {
  const { host, redis, celery, captured_at } = data;
  return (
    <>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 'var(--pad, 16px)',
        }}
      >
        {/* LEFT — host */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <MiniMeter percent={host.cpu_percent} label="CPU" />
          <MiniMeter percent={host.memory_percent} label="Memory" />
          <StatRow
            label="Memory used"
            value={`${host.memory_used_mb.toLocaleString()} / ${host.memory_total_mb.toLocaleString()} MB`}
          />
          <StatRow label="Threads" value={host.thread_count.toLocaleString()} />
        </div>

        {/* RIGHT — redis + celery */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', fontSize: 12 }}>
            <ConnectedDot ok={redis.connected} />
            <span style={{ color: 'var(--text-3)' }}>
              Redis {redis.connected ? 'connected' : 'disconnected'}
            </span>
          </div>
          <StatRow
            label="Queue depth"
            value={redis.queue_depth.toLocaleString()}
          />
          <StatRow
            label="Active tasks"
            value={celery.active_tasks.toLocaleString()}
          />
          <StatRow
            label="Scheduled tasks"
            value={celery.scheduled_tasks.toLocaleString()}
          />
          <StatRow
            label="Workers online"
            value={celery.workers_online.toLocaleString()}
          />
        </div>
      </div>

      <div
        style={{
          marginTop: 14,
          paddingTop: 10,
          borderTop: '1px solid rgba(255,255,255,0.06)',
          fontSize: 11,
          color: 'var(--text-3)',
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <span>Updated {formatTimestamp(captured_at)}</span>
        <span>polls every 5s</span>
      </div>
    </>
  );
}

export default function SystemMetricsCard() {
  const query = useSystemMetrics();

  if (query.isPending) {
    return (
      <CardShell>
        <p className="text-muted" style={{ margin: 0 }}>
          Loading system metrics…
        </p>
      </CardShell>
    );
  }

  if (query.isError) {
    return (
      <CardShell>
        <p style={{ color: 'var(--error, #f87171)', margin: 0 }}>
          Failed to load system metrics
          {query.error instanceof Error ? `: ${query.error.message}` : '.'}
        </p>
      </CardShell>
    );
  }

  if (!query.data) {
    return (
      <CardShell>
        <p className="text-muted" style={{ margin: 0 }}>
          No data.
        </p>
      </CardShell>
    );
  }

  return (
    <CardShell>
      <Body data={query.data} />
    </CardShell>
  );
}
