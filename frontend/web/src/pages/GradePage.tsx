// GradePage — list of SEO grading runs.
//
// Shows the most recent ~50 runs in a table with status pill, score,
// timestamp, cost. Each row links to /grade/<id>. The "Run new grade"
// button kicks off a fresh run via the same useStartGrade mutation
// the Overview page uses.

import { Link, useLocation } from 'wouter';
import { useGradeList, useStartGrade } from '../api/hooks/useGrade';
import type { SEORun } from '../api/seoTypes';

export default function GradePage() {
  const [, setLocation] = useLocation();
  const { data, isLoading, isError } = useGradeList();
  const startGrade = useStartGrade();

  function handleRunGrade() {
    startGrade.mutate(
      { sync: false },
      {
        onSuccess: (resp) => setLocation(`/grade/${resp.id}`),
      },
    );
  }

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>SEO Grade history</h1>
          <div className="seo-page-sub">
            Every run is reproducible — sources, model versions, and
            agent conversation are stored with each grade.
          </div>
        </div>
        <button
          className="seo-btn"
          onClick={handleRunGrade}
          disabled={startGrade.isPending}
        >
          {startGrade.isPending ? 'Starting…' : 'Run new grade'}
        </button>
      </header>

      {startGrade.isError && (
        <div className="seo-error">
          {startGrade.error instanceof Error
            ? startGrade.error.message
            : 'Failed to start run.'}
        </div>
      )}

      <div className="seo-card">
        {isLoading && <div className="seo-empty">Loading…</div>}
        {isError && (
          <div className="seo-error">Could not load run history.</div>
        )}
        {data && data.length === 0 && (
          <div className="seo-empty">
            <b>No runs yet.</b>
            <div style={{ marginTop: 4 }}>
              Click "Run new grade" above to produce the first one.
            </div>
          </div>
        )}
        {data && data.length > 0 && (
          <table className="seo-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Domain</th>
                <th className="num">Score</th>
                <th>Started</th>
                <th>Findings</th>
                <th className="num">Cost (USD)</th>
                <th>Run ID</th>
              </tr>
            </thead>
            <tbody>
              {data.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function RunRow({ run }: { run: SEORun }) {
  return (
    <tr
      style={{ cursor: 'pointer' }}
      onClick={() => {
        window.location.hash = `#/grade/${run.id}`;
      }}
    >
      <td>
        <span className={`seo-run-status ${run.status}`}>{run.status}</span>
      </td>
      <td>{run.domain}</td>
      <td className="num">
        <b>{run.overall_score?.toFixed(1) ?? '—'}</b>
      </td>
      <td>{formatTime(run.started_at)}</td>
      <td>{run.findings_count}</td>
      <td className="num">{run.total_cost_usd.toFixed(4)}</td>
      <td>
        <Link
          href={`/grade/${run.id}`}
          style={{
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: 11,
            color: 'var(--accent)',
          }}
        >
          {run.id.slice(0, 8)}
        </Link>
      </td>
    </tr>
  );
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
