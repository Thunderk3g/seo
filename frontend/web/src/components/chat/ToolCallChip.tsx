// One collapsed chip per tool call. Click to expand the args + result.

import { useState } from 'react';
import type { ChatToolCall } from '../../api/seoTypes';

const PRETTY_NAMES: Record<string, string> = {
  get_gsc_summary: 'Search Console snapshot',
  get_semrush_keywords: 'SEMrush keywords',
  get_sitemap_pages: 'Sitemap pages',
  get_competitor_gap: 'Competitor gap',
  get_crawler_status: 'Crawler status',
  get_crawler_summary: 'Crawler summary',
  get_latest_grade: 'Latest grade',
  run_grade_async: 'Start grading run',
  emit_card: 'Card',
};

export default function ToolCallChip({ call }: { call: ChatToolCall }) {
  const [open, setOpen] = useState(false);
  const ok =
    call.result &&
    typeof call.result === 'object' &&
    (call.result as { ok?: boolean }).ok !== false;
  const label = PRETTY_NAMES[call.name] || call.name;
  return (
    <div className={`chat-tool-chip ${open ? 'open' : ''} ${ok ? '' : 'err'}`}>
      <button
        type="button"
        className="chat-tool-chip-head"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="chat-tool-chip-icon">{ok ? '✓' : '!'}</span>
        <span className="chat-tool-chip-label">{label}</span>
        <span className="chat-tool-chip-name">{call.name}</span>
        <span className="chat-tool-chip-toggle">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="chat-tool-chip-body">
          {Object.keys(call.args || {}).length > 0 && (
            <>
              <div className="chat-tool-chip-section">arguments</div>
              <pre>{JSON.stringify(call.args, null, 2)}</pre>
            </>
          )}
          <div className="chat-tool-chip-section">result</div>
          <pre>{JSON.stringify(call.result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
