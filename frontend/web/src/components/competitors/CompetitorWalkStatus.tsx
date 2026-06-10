import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';

const BLUE = '#0072ce';
const NAVY = '#002c6e';

interface ActiveTask {
  task_id: string;
  name: string;
  domain: string;
  pages: number | null;
}

interface RunningSnap {
  domain: string;
  kind: string;
  pages: number;
  started_at: string | null;
}

interface WalkStatus {
  is_running: boolean;
  paused: boolean;
  active_tasks: ActiveTask[];
  running_snapshots: RunningSnap[];
}

const TASK_LABEL: Record<string, string> = {
  'seo_ai.walk_competitor': 'Competitor',
  'seo_ai.walk_competitor_roster': 'Roster (all competitors)',
  'seo_ai.crawl_own_content': 'Own content',
};

/**
 * Live competitor / content walk status + stop control. Polls every 5 s
 * while anything is running, every 30 s otherwise. The Stop button
 * revokes in-flight walks and sets the pause flag; partial pages already
 * crawled are kept.
 */
export default function CompetitorWalkStatus() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['competitor-walk-status'],
    queryFn: () => api.get<WalkStatus>('/seo/competitors/walk-status/'),
    refetchInterval: (q) => (q.state.data?.is_running ? 5_000 : 30_000),
  });
  const stop = useMutation({
    mutationFn: () => api.post('/seo/competitors/walk-stop/'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['competitor-walk-status'] }),
  });

  if (!data) return null;
  const running = data.is_running;

  return (
    <section
      style={{
        border: `1px solid ${running ? BLUE : '#e2e8f0'}`,
        background: running ? '#f0f7ff' : '#f8fafc',
        borderRadius: 10,
        padding: '12px 16px',
        margin: '12px 0',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 700, color: NAVY, fontSize: 14 }}>
          {running ? '● Competitor crawl running' : 'Competitor crawl idle'}
        </span>
        {data.paused && (
          <span style={{ fontSize: 11.5, fontWeight: 700, color: '#b45309', background: '#fef3c7', borderRadius: 999, padding: '1px 9px' }}>
            paused
          </span>
        )}
        <button
          type="button"
          onClick={() => stop.mutate()}
          disabled={!running || stop.isPending}
          style={{
            marginLeft: 'auto',
            background: running ? '#b91c1b' : '#cbd5e1',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            padding: '6px 14px',
            fontWeight: 700,
            fontSize: 12.5,
            cursor: running ? 'pointer' : 'default',
          }}
        >
          {stop.isPending ? 'Stopping…' : 'Stop crawl'}
        </button>
      </div>

      {data.active_tasks.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {data.active_tasks.map((t) => (
            <div key={t.task_id} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#1e40af', background: '#dbeafe', borderRadius: 6, padding: '1px 8px' }}>
                {TASK_LABEL[t.name] ?? t.name}
              </span>
              <span style={{ fontWeight: 600, color: NAVY }}>
                {t.domain || '(discovering…)'}
              </span>
              {t.pages !== null && (
                <span style={{ color: '#475569' }}>
                  {t.pages.toLocaleString()} pages so far
                </span>
              )}
              <span className="cc-pulse" style={{ width: 8, height: 8, borderRadius: 999, background: BLUE }} />
            </div>
          ))}
        </div>
      )}

      {data.active_tasks.length === 0 && data.running_snapshots.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12.5, color: '#475569' }}>
          {data.running_snapshots.map((s) => (
            <span key={s.domain + (s.started_at || '')} style={{ marginRight: 14 }}>
              <b style={{ color: NAVY }}>{s.domain || s.kind}</b>: {s.pages.toLocaleString()} pages
            </span>
          ))}
        </div>
      )}

      {stop.isSuccess && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#16a34a' }}>
          Stop signal sent — crawled pages so far are kept.
        </div>
      )}
    </section>
  );
}
