// SettingRow — single-row primitive used inside `.settings-card` blocks
// on the SettingsPage. Mirrors `.design-ref/project/pages.jsx:660–679`
// and consumes the `.setting-row` / `.setting-label` / `.setting-hint`
// / `.setting-value` rules already present in `styles/lattice.css`
// (lines 1233–1242 of that file). No inline styles needed for the row
// frame itself; the only inline use is the optional `[data-off="1"]`
// dimming and the inline-error tone, both kept tiny so the component
// stays a layout primitive rather than a stylesheet.
//
// Composition contract:
//   • `label`   — left column (always shown).
//   • `hint`    — muted line under the label.
//   • `value`   — right column. Accepts any ReactNode so callers can
//                 drop in raw text, an <input>, a <textarea>, or a
//                 segmented control without nested wrappers.
//   • `toggle`  — convenience: when set, replaces `value` with a
//                 <TogglePill>. Passing both `toggle` and `value` is
//                 valid; the toggle wins (matches the ref).
//   • `mono`    — render `value` (when it's a string) in the .mono
//                 typeface. Ignored when `value` is a ReactNode.
//   • `badge`   — small status pill rendered before the value. Uses
//                 the existing `.status-online` + `.status-dot` chips.
//   • `off`     — visually mute the whole row (paired with the
//                 `data-off="1"` selector — already styled, but if
//                 your environment doesn't define one, the inline
//                 fallback below covers it).
//   • `error`   — when present, renders an inline error line below the
//                 row in the error tone. The row also gets
//                 `data-error="1"` for any future styling.

import type { ReactNode } from 'react';
import TogglePill from './TogglePill';

interface SettingRowProps {
  label: string;
  value?: ReactNode;
  hint?: string;
  toggle?: {
    checked: boolean;
    onChange: (next: boolean) => void;
    ariaLabel?: string;
  };
  off?: boolean;
  mono?: boolean;
  badge?: string;
  error?: string;
}

export default function SettingRow({
  label,
  value,
  hint,
  toggle,
  off,
  mono,
  badge,
  error,
}: SettingRowProps) {
  // String values get the optional .mono treatment via a span. ReactNode
  // values pass through untouched — letting callers wrap their own
  // <input>/<textarea>/<SegmentedControl> without our markup interfering.
  const isStringValue = typeof value === 'string' || typeof value === 'number';
  const renderedValue: ReactNode = toggle ? (
    <TogglePill
      checked={toggle.checked}
      onChange={toggle.onChange}
      ariaLabel={toggle.ariaLabel ?? label}
    />
  ) : isStringValue ? (
    <span className={mono ? 'mono' : undefined}>{value}</span>
  ) : (
    value
  );

  return (
    <>
      <div
        className="setting-row"
        // `data-off` is a hook for any future muted-row CSS; we also set
        // an inline opacity fallback so the visual cue lands even without
        // the selector. `data-error` is purely informational for now.
        data-off={off ? '1' : undefined}
        data-error={error ? '1' : undefined}
        style={off ? { opacity: 0.6 } : undefined}
      >
        <div>
          <div className="setting-label">{label}</div>
          {hint && <div className="setting-hint">{hint}</div>}
        </div>
        <div className="setting-value">
          {badge && (
            <span className="status-online" style={{ marginRight: 8 }}>
              <span className="status-dot" />
              {badge}
            </span>
          )}
          {renderedValue}
        </div>
      </div>
      {error && (
        <div
          role="alert"
          className="setting-row"
          // Match the row's left-padding so the error sits under the value
          // column visually without inheriting the bottom border (we hide
          // it via inline override since this is the *trailing* row of a
          // pair logically).
          style={{
            color: 'var(--error, #f87171)',
            fontSize: 11,
            paddingTop: 0,
            paddingBottom: 8,
            borderBottom: 0,
          }}
        >
          <div />
          <div>{error}</div>
        </div>
      )}
    </>
  );
}
