// TogglePill — pill-shaped two-state switch used wherever the SettingsPage
// (and any future settings-style surface) needs an on/off control.
//
// Visual contract lives in `styles/lattice.css` (`.toggle-pill` rules at
// lines 1244–1262 of that file): a 30×18 pill whose inner `<i/>` knob
// translates 12px on the X axis when `data-on="1"`. Background flips to
// `var(--accent)` in the on state. We render a real <button> (rather than
// a styled <input type="checkbox">) so the slide animation and accent
// fill come from CSS directly, matching the design-ref pages.jsx:670.

interface TogglePillProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  ariaLabel?: string;
}

export default function TogglePill({
  checked,
  onChange,
  ariaLabel,
}: TogglePillProps) {
  return (
    <button
      // Inside a <form>, omitting `type` defaults to "submit" which would
      // fire the form's onSubmit on every toggle click — not what we want.
      type="button"
      className="toggle-pill"
      data-on={checked ? '1' : '0'}
      aria-pressed={checked}
      aria-label={ariaLabel}
      onClick={() => onChange(!checked)}
    >
      <i />
    </button>
  );
}
