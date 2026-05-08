// AIInsightsDrawer.tsx — slide-over panel anchored to the right edge.
//
// Day 5: the drawer is the only consumer of useInsights. It fires the
// query lazily (enabled=open) and renders three states:
//   1. Loading — spinner.
//   2. Error — banner with the API error message.
//   3. Success — summary paragraph + severity-tagged highlight cards.
//      When `available === false`, we swap to a friendly "not configured"
//      placeholder rather than a confusing empty state.
//
// All styling uses existing CSS tokens from styles/lattice.css (var(--…)).
// No new dependencies.

import type { CSSProperties } from 'react';
import Icon from './icons/Icon';
import { useInsights, useRegenerateInsights } from '../api/hooks/useInsights';
import type { InsightHighlight, InsightSeverity } from '../api/types';

interface AIInsightsDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string | null;
}

const SEVERITY_COLOR: Record<InsightSeverity, string> = {
  info: 'var(--notice)',
  warning: 'var(--warning)',
  critical: 'var(--error)',
};

const overlayStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(0,0,0,0.4)',
  zIndex: 40,
};

const panelStyle: CSSProperties = {
  position: 'fixed',
  top: 0,
  right: 0,
  bottom: 0,
  width: 'min(440px, 92vw)',
  background: 'var(--surface)',
  borderLeft: '1px solid var(--border-2)',
  display: 'flex',
  flexDirection: 'column',
  zIndex: 41,
  boxShadow: '-12px 0 32px rgba(0,0,0,0.3)',
};

const headerStyle: CSSProperties = {
  padding: '14px 16px',
  borderBottom: '1px solid var(--border)',
  display: 'flex',
  alignItems: 'center',
  gap: 10,
};

const bodyStyle: CSSProperties = {
  padding: 16,
  overflowY: 'auto',
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
  flex: 1,
};

const highlightCardStyle = (severity: InsightSeverity): CSSProperties => ({
  padding: 12,
  borderRadius: 'var(--radius)',
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  borderLeft: `3px solid ${SEVERITY_COLOR[severity]}`,
});

const badgeStyle = (severity: InsightSeverity): CSSProperties => ({
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: 999,
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: 0.4,
  color: SEVERITY_COLOR[severity],
  border: `1px solid ${SEVERITY_COLOR[severity]}`,
  background: 'transparent',
});

function HighlightCard({ h }: { h: InsightHighlight }) {
  return (
    <div style={highlightCardStyle(h.severity)}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}
      >
        <span style={badgeStyle(h.severity)}>{h.severity}</span>
        <strong style={{ fontSize: 13 }}>{h.title}</strong>
      </div>
      <div style={{ color: 'var(--text-2)', fontSize: 12, lineHeight: 1.55 }}>
        {h.body}
      </div>
    </div>
  );
}

export default function AIInsightsDrawer({
  open,
  onClose,
  sessionId,
}: AIInsightsDrawerProps) {
  // Lazy: only fire the query once the drawer is actually open.
  const query = useInsights(sessionId, open);
  const regenerate = useRegenerateInsights();

  if (!open) return null;

  const data = query.data;
  const isPending = query.isLoading || query.isFetching;
  const isError = query.isError;
  const isRegenerating = regenerate.isPending;

  const handleRegenerate = () => {
    if (!sessionId || isRegenerating) return;
    regenerate.mutate(sessionId);
  };

  return (
    <>
      {/* Self-contained keyframes so the spinner animates without touching
          lattice.css. Scoped only by name; harmless if redefined elsewhere. */}
      <style>{'@keyframes ai-insights-spin { to { transform: rotate(360deg); } }'}</style>
      <div style={overlayStyle} onClick={onClose} aria-hidden />
      <aside
        style={panelStyle}
        role="dialog"
        aria-modal="true"
        aria-label="AI Insights"
      >
        <header style={headerStyle}>
          <Icon name="zap" size={15} />
          <strong style={{ fontSize: 14, flex: 1 }}>AI Insights</strong>
          {data?.cached && (
            <span
              style={{
                fontSize: 11,
                color: 'var(--text-3)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '2px 6px',
              }}
              title="Cached payload — POST to regenerate"
            >
              cached
            </span>
          )}
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={!sessionId || isRegenerating}
            aria-label={isRegenerating ? 'Regenerating insights' : 'Regenerate insights'}
            title="Force a fresh Anthropic call and overwrite the cache"
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: '4px 10px',
              borderRadius: 6,
              border: '1px solid var(--border-2)',
              background: 'var(--surface-2)',
              color: 'var(--text)',
              cursor: !sessionId || isRegenerating ? 'not-allowed' : 'pointer',
              opacity: !sessionId || isRegenerating ? 0.6 : 1,
            }}
          >
            {isRegenerating ? 'Regenerating…' : 'Regenerate'}
          </button>
          <button
            className="icon-btn"
            aria-label="Close insights"
            onClick={onClose}
          >
            <Icon name="plus" size={14} style={{ transform: 'rotate(45deg)' }} />
          </button>
        </header>

        <div style={bodyStyle}>
          {!sessionId && (
            <div className="text-muted" style={{ fontSize: 12 }}>
              Select a crawl session to see insights.
            </div>
          )}

          {sessionId && isPending && !data && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                color: 'var(--text-2)',
                fontSize: 12,
              }}
            >
              <span
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  border: '2px solid var(--border-2)',
                  borderTopColor: 'var(--accent)',
                  animation: 'ai-insights-spin 0.9s linear infinite',
                  display: 'inline-block',
                }}
              />
              Generating insights…
            </div>
          )}

          {sessionId && isError && (
            <div
              role="alert"
              style={{
                padding: 10,
                borderRadius: 'var(--radius)',
                border: '1px solid var(--error)',
                color: 'var(--error)',
                fontSize: 12,
                background: 'rgba(248,113,113,0.08)',
              }}
            >
              {query.error instanceof Error
                ? query.error.message
                : 'Failed to load AI insights.'}
            </div>
          )}

          {sessionId && data && data.available === false && (
            <div style={{ color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text)' }}>
                AI insights are not configured.
              </strong>
              <p style={{ marginTop: 8 }}>{data.summary}</p>
              <p style={{ color: 'var(--text-3)', fontSize: 12, marginTop: 8 }}>
                Set <code className="mono">ANTHROPIC_API_KEY</code> on the
                backend to enable this feature.
              </p>
            </div>
          )}

          {sessionId && data && data.available && (
            <>
              <p style={{ fontSize: 13, lineHeight: 1.6, margin: 0 }}>
                {data.summary}
              </p>
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                }}
              >
                {data.highlights.length === 0 ? (
                  <div className="text-muted" style={{ fontSize: 12 }}>
                    No highlights produced for this session.
                  </div>
                ) : (
                  data.highlights.map((h, i) => (
                    <HighlightCard key={i} h={h} />
                  ))
                )}
              </div>
              <div
                style={{
                  marginTop: 'auto',
                  paddingTop: 10,
                  borderTop: '1px solid var(--border)',
                  color: 'var(--text-3)',
                  fontSize: 11,
                }}
              >
                {data.model} · {new Date(data.generated_at).toLocaleString()}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
