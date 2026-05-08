// AIInsightsDrawer.tsx — frosted floating "tweaks-panel" pill.
//
// Spec §5.4.9: this is NOT a full-height side modal. It's a small,
// frosted-glass card pinned to the bottom-right corner with a draggable
// header — visual styling lifted from .design-ref/project/tweaks-panel.jsx
// (the .twk-* class system). No backdrop / overlay; the rest of the UI
// stays interactive while the panel is open.
//
// Three states:
//   1. Loading      — chrome + "Generating…" body line.
//   2. Error        — chrome + inline error pill.
//   3. available=false — env-gated friendly placeholder.
//   4. Success      — summary section + per-highlight rows + footer
//                      showing model + generated_at.
//
// All styles are inlined via a scoped <style> block (see TWK_STYLE below)
// so we avoid touching styles/lattice.css. The class names are unique
// enough (.twk-*, .ai-insights-*) that they won't collide.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useInsights, useRegenerateInsights } from '../api/hooks/useInsights';
import type { InsightHighlight, InsightSeverity } from '../api/types';

interface AIInsightsDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string | null;
}

const SEVERITY_COLOR: Record<InsightSeverity, string> = {
  info: 'var(--notice, #60a5fa)',
  warning: 'var(--warning, #f59e0b)',
  critical: 'var(--error, #f87171)',
};

// Inline stylesheet — mirrors the visual structure of tweaks-panel.jsx
// adapted to the dark Lattice palette.
const TWK_STYLE = `
.ai-insights-panel {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 1000;
  width: min(360px, calc(100vw - 32px));
  max-height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
  background: rgba(20, 22, 28, 0.85);
  -webkit-backdrop-filter: blur(24px) saturate(160%);
  backdrop-filter: blur(24px) saturate(160%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.04) inset,
    0 12px 40px rgba(0, 0, 0, 0.5);
  color: var(--text, #e6e8ec);
  overflow: hidden;
  font-size: 13px;
  line-height: 1.45;
}
.ai-insights-panel .twk-hd {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 8px 10px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  cursor: move;
  user-select: none;
}
.ai-insights-panel .twk-hd b {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.01em;
  flex: 1;
}
.ai-insights-panel .pill {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-2, #a8adb8);
}
.ai-insights-panel .twk-x {
  appearance: none;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: 0;
  background: transparent;
  color: var(--text-2, #a8adb8);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  flex-shrink: 0;
}
.ai-insights-panel .twk-x:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text, #e6e8ec);
}
.ai-insights-panel .twk-x:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ai-insights-panel .twk-x.spin {
  animation: ai-insights-spin 0.9s linear infinite;
}
.ai-insights-panel .twk-body {
  padding: 12px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.15) transparent;
}
.ai-insights-panel .twk-body::-webkit-scrollbar { width: 8px; }
.ai-insights-panel .twk-body::-webkit-scrollbar-track { background: transparent; margin: 2px; }
.ai-insights-panel .twk-body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 4px;
  border: 2px solid transparent;
  background-clip: content-box;
}
.ai-insights-panel .twk-body::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.25);
  border: 2px solid transparent;
  background-clip: content-box;
}
.ai-insights-panel .twk-sect { display: flex; flex-direction: column; gap: 6px; }
.ai-insights-panel .twk-sect-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3, #6b7280);
  margin-bottom: 2px;
}
.ai-insights-panel .twk-sect p { margin: 0; color: var(--text, #e6e8ec); }
.ai-insights-panel .twk-row {
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ai-insights-panel .twk-row-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text, #e6e8ec);
}
.ai-insights-panel .twk-row-body {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2, #a8adb8);
}
.ai-insights-panel .twk-foot {
  padding-top: 4px;
  font-size: 10px;
  color: var(--text-3, #6b7280);
  letter-spacing: 0.02em;
}
.ai-insights-panel .err-pill {
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: var(--error, #f87171);
  font-size: 12px;
}
.ai-insights-panel .muted {
  color: var(--text-2, #a8adb8);
  font-size: 12px;
  margin: 0;
}
@keyframes ai-insights-spin { to { transform: rotate(360deg); } }
`;

function HighlightRow({ h }: { h: InsightHighlight }) {
  return (
    <div
      className="twk-row"
      style={{ borderLeft: `3px solid ${SEVERITY_COLOR[h.severity]}` }}
    >
      <div className="twk-row-title">{h.title}</div>
      <div className="twk-row-body">{h.body}</div>
    </div>
  );
}

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function AIInsightsDrawer({
  open,
  onClose,
  sessionId,
}: AIInsightsDrawerProps) {
  // Lazy fetch — only fire once the panel is actually open.
  const query = useInsights(sessionId, open);
  const regenerate = useRegenerateInsights();

  // Drag state — track right/bottom offsets so the panel stays anchored
  // to the bottom-right corner just like the reference implementation.
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ right: number; bottom: number }>({
    right: 16,
    bottom: 16,
  });
  const dragRef = useRef<{
    startX: number;
    startY: number;
    startRight: number;
    startBottom: number;
  } | null>(null);

  const PAD = 8;

  const onDragStart = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      // Only start dragging from the header itself, not from buttons inside.
      if ((e.target as HTMLElement).closest('button')) return;
      e.preventDefault();
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startRight: pos.right,
        startBottom: pos.bottom,
      };
      const onMove = (ev: MouseEvent) => {
        if (!dragRef.current || !panelRef.current) return;
        const w = panelRef.current.offsetWidth;
        const h = panelRef.current.offsetHeight;
        const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
        const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
        const nextRight = dragRef.current.startRight - (ev.clientX - dragRef.current.startX);
        const nextBottom = dragRef.current.startBottom - (ev.clientY - dragRef.current.startY);
        setPos({
          right: Math.min(maxRight, Math.max(PAD, nextRight)),
          bottom: Math.min(maxBottom, Math.max(PAD, nextBottom)),
        });
      };
      const onUp = () => {
        dragRef.current = null;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [pos.right, pos.bottom],
  );

  // Clamp on viewport resize so the panel never gets stuck off-screen.
  useEffect(() => {
    if (!open) return undefined;
    const clamp = () => {
      if (!panelRef.current) return;
      const w = panelRef.current.offsetWidth;
      const h = panelRef.current.offsetHeight;
      const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
      const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
      setPos((p) => ({
        right: Math.min(maxRight, Math.max(PAD, p.right)),
        bottom: Math.min(maxBottom, Math.max(PAD, p.bottom)),
      }));
    };
    window.addEventListener('resize', clamp);
    return () => window.removeEventListener('resize', clamp);
  }, [open]);

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
      <style>{TWK_STYLE}</style>
      <div
        ref={panelRef}
        className="ai-insights-panel"
        role="complementary"
        aria-label="AI Insights"
        style={{ right: pos.right, bottom: pos.bottom }}
      >
        <div className="twk-hd" onMouseDown={onDragStart}>
          <b>AI Insights</b>
          {data?.cached && (
            <span className="pill" title="Cached payload — regenerate for a fresh call">
              cached
            </span>
          )}
          <button
            type="button"
            className={`twk-x ${isRegenerating ? 'spin' : ''}`}
            onClick={handleRegenerate}
            disabled={!sessionId || isRegenerating}
            aria-label={isRegenerating ? 'Regenerating insights' : 'Regenerate insights'}
            title="Regenerate"
          >
            {'↻'}
          </button>
          <button
            type="button"
            className="twk-x"
            onClick={onClose}
            aria-label="Close insights"
            title="Close"
          >
            {'×'}
          </button>
        </div>

        <div className="twk-body">
          {!sessionId && (
            <p className="muted">Select a crawl session to see insights.</p>
          )}

          {sessionId && isPending && !data && (
            <p className="muted">Generating…</p>
          )}

          {sessionId && isError && (
            <div role="alert" className="err-pill">
              {query.error instanceof Error
                ? query.error.message
                : 'Failed to load AI insights.'}
            </div>
          )}

          {sessionId && data && data.available === false && (
            <section className="twk-sect">
              <div className="twk-sect-label">Not configured</div>
              <p>
                AI insights are not configured. Set{' '}
                <code className="mono">ANTHROPIC_API_KEY</code> on the backend
                to enable this feature.
              </p>
            </section>
          )}

          {sessionId && data && data.available && (
            <>
              <section className="twk-sect">
                <div className="twk-sect-label">Summary</div>
                <p>{data.summary}</p>
              </section>

              <section className="twk-sect">
                <div className="twk-sect-label">Top Issues</div>
                {data.highlights.length === 0 ? (
                  <p className="muted">No highlights produced for this session.</p>
                ) : (
                  data.highlights.map((h, i) => (
                    <HighlightRow key={`${h.title}-${i}`} h={h} />
                  ))
                )}
              </section>

              <div className="twk-foot">
                {data.model} {'·'} {formatTime(data.generated_at)}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
