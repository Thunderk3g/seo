// GradeDetailPage — one grading run.
//
// Three tabs in the right pane:
//   - Findings    full table, filterable by agent
//   - Narrative   the executive summary + recommended action
//   - Conversation the agent-to-agent message log (audit trail)
//
// Left pane carries the score gauge, sub-score grid, and the meta strip
// (status, cost, sources). Useful for SEO leads who want one URL they
// can hand to leadership.

import { useState } from 'react';
import { Link, useRoute } from 'wouter';
import ScoreGauge from '../components/seo/ScoreGauge';
import SubScoreGrid, {
  SUB_SCORE_LABELS,
} from '../components/seo/SubScoreGrid';
import {
  useGrade,
  useGradeFindings,
  useGradeMessages,
} from '../api/hooks/useGrade';
import type { SEORun, SEORunFinding, SEORunMessage } from '../api/seoTypes';

type AgentFilter = 'all' | 'technical' | 'keyword' | 'content' | 'competitor';
type Tab = 'findings' | 'narrative' | 'conversation';

export default function GradeDetailPage() {
  const [, params] = useRoute<{ id: string }>('/grade/:id');
  const id = params?.id ?? null;
  const { data: run, isLoading, isError } = useGrade(id);
  const [tab, setTab] = useState<Tab>('findings');
  const [agent, setAgent] = useState<AgentFilter>('all');

  if (!id) return <div className="seo-empty">No run id.</div>;
  if (isLoading) return <div className="seo-empty">Loading run…</div>;
  if (isError || !run) return <div className="seo-error">Could not load run.</div>;

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>SEO Grade · {run.domain}</h1>
          <div className="seo-page-sub" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className={`seo-run-status ${run.status}`}>{run.status}</span>
            <span>Started {formatTime(run.started_at)}</span>
            {run.finished_at && (
              <span>· Finished {formatTime(run.finished_at)}</span>
            )}
            <span>· Cost ${run.total_cost_usd.toFixed(4)}</span>
          </div>
        </div>
        <Link href="/grade" className="seo-btn seo-btn-ghost">
          ← Back to history
        </Link>
      </header>

      <div className="seo-detail-grid">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <RunSummaryCard run={run} />
          <RunMetaCard run={run} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          <div className="seo-tab-strip">
            <button
              className={`seo-tab ${tab === 'findings' ? 'active' : ''}`}
              onClick={() => setTab('findings')}
            >
              Findings · {run.findings_count}
            </button>
            <button
              className={`seo-tab ${tab === 'narrative' ? 'active' : ''}`}
              onClick={() => setTab('narrative')}
            >
              Narrative
            </button>
            <button
              className={`seo-tab ${tab === 'conversation' ? 'active' : ''}`}
              onClick={() => setTab('conversation')}
            >
              Conversation
            </button>
          </div>

          <div style={{ marginTop: 16 }}>
            {tab === 'findings' && (
              <FindingsTab
                id={run.id}
                agent={agent}
                onAgentChange={setAgent}
              />
            )}
            {tab === 'narrative' && <NarrativeTab run={run} />}
            {tab === 'conversation' && <ConversationTab id={run.id} />}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── left pane ───────────────────────────────────────────────────────────

function RunSummaryCard({ run }: { run: SEORun }) {
  const order = [
    'technical',
    'content',
    'backlinks',
    'core_web_vitals',
    'internal_linking',
    'serp_ctr',
    'structured_data',
    'indexability',
  ];
  const entries = order.map((k) => ({
    key: k,
    label: SUB_SCORE_LABELS[k] ?? k,
    value: (run.sub_scores as Record<string, number | undefined>)[k],
  }));
  return (
    <div className="seo-card seo-elev-2">
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <ScoreGauge score={run.overall_score} size={160} />
      </div>
      <div style={{ marginTop: 8 }}>
        <SubScoreGrid entries={entries.slice(0, 4)} />
      </div>
      <div style={{ marginTop: 8 }}>
        <SubScoreGrid entries={entries.slice(4)} />
      </div>
    </div>
  );
}

function RunMetaCard({ run }: { run: SEORun }) {
  const provider = run.model_versions.provider ?? '—';
  const model = run.model_versions.model ?? '—';
  const sources = run.sources_snapshot;
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Run metadata</h2>
      </div>
      <table className="seo-table">
        <tbody>
          <tr>
            <td>LLM provider</td>
            <td className="num">{provider}</td>
          </tr>
          <tr>
            <td>Model</td>
            <td className="num" style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
              {model}
            </td>
          </tr>
          <tr>
            <td>Triggered by</td>
            <td className="num">{run.triggered_by}</td>
          </tr>
          <tr>
            <td>Run ID</td>
            <td className="num" style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5 }}>
              {run.id.slice(0, 8)}…
            </td>
          </tr>
          {typeof sources?.semrush_database === 'string' && (
            <tr>
              <td>SEMrush DB</td>
              <td className="num">{sources.semrush_database as string}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── right pane: findings ────────────────────────────────────────────────

function FindingsTab({
  id,
  agent,
  onAgentChange,
}: {
  id: string;
  agent: AgentFilter;
  onAgentChange: (a: AgentFilter) => void;
}) {
  const { data, isLoading } = useGradeFindings(
    id,
    agent === 'all' ? null : agent,
  );
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Findings</h2>
        <select
          value={agent}
          onChange={(e) => onAgentChange(e.target.value as AgentFilter)}
          style={{
            background: 'var(--surface-2)',
            border: '1px solid var(--border-2)',
            borderRadius: 7,
            padding: '4px 10px',
            font: 'inherit',
            fontSize: 12,
            color: 'var(--text)',
          }}
        >
          <option value="all">All agents</option>
          <option value="technical">Technical</option>
          <option value="keyword">Keyword</option>
          <option value="content">Content</option>
          <option value="competitor">Competitor</option>
        </select>
      </div>
      {isLoading && <div className="seo-empty">Loading…</div>}
      {data && data.length === 0 && (
        <div className="seo-empty">No findings.</div>
      )}
      {data && data.length > 0 && (
        <div className="seo-finding-list">
          {data.map((f) => (
            <FindingRow key={f.id} f={f} />
          ))}
        </div>
      )}
    </div>
  );
}

function FindingRow({ f }: { f: SEORunFinding }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="seo-finding" onClick={() => setOpen((v) => !v)} style={{ cursor: 'pointer' }}>
      <div className={`seo-finding-bar ${f.severity}`} />
      <div>
        <div className="seo-finding-title">{f.title}</div>
        <div className="seo-finding-meta">
          <span className={`seo-finding-chip ${f.severity}`}>{f.severity}</span>
          <span className="seo-finding-agent">
            {f.agent} · {f.category} · impact {f.impact} · effort {f.effort}
          </span>
        </div>
        {open && (
          <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.55 }}>
            {f.description && <p style={{ margin: '0 0 8px' }}>{f.description}</p>}
            {f.recommendation && (
              <p style={{ margin: 0 }}>
                <b style={{ color: 'var(--accent)' }}>Recommendation: </b>
                {f.recommendation}
              </p>
            )}
            {f.evidence_refs.length > 0 && (
              <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
                <b>Evidence:</b>{' '}
                {f.evidence_refs.map((ref) => (
                  <code
                    key={ref}
                    style={{
                      background: 'var(--surface-3)',
                      padding: '2px 6px',
                      borderRadius: 4,
                      marginRight: 6,
                      fontSize: 10.5,
                    }}
                  >
                    {ref}
                  </code>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="seo-finding-priority">P{f.priority}</div>
    </div>
  );
}

// ── right pane: narrative ───────────────────────────────────────────────

function NarrativeTab({ run }: { run: SEORun }) {
  const nar = run.model_versions.narrative;
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Executive narrative</h2>
      </div>
      {!nar?.executive_summary ? (
        <div className="seo-empty">No narrative was produced for this run.</div>
      ) : (
        <>
          <p
            style={{
              fontSize: 14,
              lineHeight: 1.6,
              color: 'var(--text-2)',
              margin: 0,
              whiteSpace: 'pre-line',
            }}
          >
            {nar.executive_summary}
          </p>
          {nar.top_action_this_week && (
            <div
              style={{
                marginTop: 16,
                padding: '12px 14px',
                background: 'var(--accent-soft)',
                borderRadius: 10,
                fontSize: 13,
                color: 'var(--text)',
              }}
            >
              <b style={{ color: 'var(--accent)' }}>Action this week: </b>
              {nar.top_action_this_week}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── right pane: conversation ────────────────────────────────────────────

function ConversationTab({ id }: { id: string }) {
  const { data, isLoading } = useGradeMessages(id);
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Agent conversation</h2>
        <span className="seo-card-sub">
          Every LLM call + system event — replayable for audit
        </span>
      </div>
      {isLoading && <div className="seo-empty">Loading…</div>}
      {data && data.length === 0 && (
        <div className="seo-empty">No messages recorded.</div>
      )}
      {data && data.length > 0 && (
        <div className="seo-conversation">
          {data.map((m) => (
            <MessageRow key={m.id} m={m} />
          ))}
        </div>
      )}
    </div>
  );
}

function MessageRow({ m }: { m: SEORunMessage }) {
  const body =
    typeof m.content === 'string'
      ? m.content
      : JSON.stringify(m.content, null, 2);
  return (
    <div className="seo-conv-msg">
      <div className="seo-conv-head">
        <span>
          <b>{m.from_agent || m.role}</b> · step {m.step_index} · {m.role}
          {m.cost_usd > 0 && (
            <span style={{ color: 'var(--text-3)', marginLeft: 6 }}>
              · ${m.cost_usd.toFixed(4)} · in {m.tokens_in} out {m.tokens_out}
            </span>
          )}
        </span>
        <span>{formatTime(m.created_at)}</span>
      </div>
      <pre className="seo-conv-body">{truncate(body, 1600)}</pre>
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n) + '\n…';
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString();
}
