// SettingsPage — Phase 5 vertical-slice settings form.
//
// Keyed off the active site (NOT a session), per spec §5.4.7/§5.4.8:
//   GET   /api/v1/settings/?website=<uuid>
//   PATCH /api/v1/settings/?website=<uuid>  body: changed-fields-only
//
// Backend contract (mirror of services/settings_service.py:_to_dict):
//   • website_id, domain — read-only (managed via website CRUD).
//   • is_active, include_subdomains, enable_js_rendering, respect_robots_txt
//     — booleans (toggles).
//   • max_depth (0..50), max_urls_per_session (1..1_000_000),
//     concurrency (1..100) — integers.
//   • request_delay (0..60, float), request_timeout (1..300),
//     max_retries (0..10) — networking.
//   • custom_user_agent — ≤500 chars.
//
// Validation lives server-side. On 400 the API returns
//   { detail: "<field>: <reason>" }
// preserved on ApiError.body. We split on the first ": " — first segment is
// the field name (so we can render the message under the right input);
// anything without a colon falls through as a top-level error banner.
//
// excluded_paths / excluded_params (spec §5.4.8) are stored on CrawlConfig as
// JSON string lists — server validates ≤100 entries, ≤200 chars each, no
// empty entries. Rendered as two textareas (one entry per non-empty line).
// Engine-side enforcement is a follow-up; the API+UI here is storage only.
//
// Layout (post-refactor): the page is a 2-up `.settings-row` grid of
// `.settings-card` blocks, with each row inside a card rendered through
// the shared `SettingRow` primitive. Toggles use `TogglePill` rather than
// native checkboxes so the pill background animates with the active
// accent. Pairings (left, right):
//   • Identity (full-width)
//   • Crawl behaviour            | Crawl scope
//   • Networking                 | User agent
//   • Excluded paths             | Schedule (coming-soon)
//   • Appearance                 | API & integrations (coming-soon)
// The Save / Discard bar is lifted out of the form flow into a fixed
// bottom-right widget so it stays visible across long settings pages.

import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { ApiError } from '../api/client';
import { useActiveSite } from '../api/hooks/useActiveSite';
import {
  useSettings,
  useUpdateSettings,
} from '../api/hooks/useSettings';
import type { LatticePrefs, SettingsDict, SettingsUpdate } from '../api/types';
import SettingRow from '../components/SettingRow';

// ─────────────────────────────────────────────────────────────────
// Appearance preferences (spec §5.4.8/§5.4.9). Client-only — stored
// in localStorage under `lattice.prefs`, applied to <html> via a
// CSS variable (--accent) and `data-theme` / `data-density`
// dataset attributes so the reference [data-theme="light"] selectors
// in lattice.css actually match.
// ─────────────────────────────────────────────────────────────────

const LATTICE_PREFS_KEY = 'lattice.prefs';

const ACCENT_HEX: Record<LatticePrefs['accent'], string> = {
  amber: '#fbbf24',
  violet: '#a78bfa',
  cyan: '#22d3ee',
  emerald: '#6ee7b7',
};

const DEFAULT_PREFS: LatticePrefs = {
  accent: 'emerald',
  density: 'comfortable',
  theme: 'dark',
};

function loadPrefs(): LatticePrefs {
  if (typeof window === 'undefined') return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(LATTICE_PREFS_KEY);
    const parsed = JSON.parse(raw ?? 'null') as Partial<LatticePrefs> | null;
    if (!parsed) return DEFAULT_PREFS;
    return {
      accent: parsed.accent ?? DEFAULT_PREFS.accent,
      density: parsed.density ?? DEFAULT_PREFS.density,
      theme: parsed.theme ?? DEFAULT_PREFS.theme,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

function applyPrefs(prefs: LatticePrefs): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  // Accent → CSS custom property on <html>. Glow/hover variants stay
  // baked-in (lattice.css uses --accent-glow, --accent-hover); we
  // recompute those here so the whole UI tracks the new accent.
  const hex = ACCENT_HEX[prefs.accent];
  root.style.setProperty('--accent', hex);
  root.style.setProperty('--accent-hover', hex);
  // accent-glow = same hex at ~18% alpha; pre-baked rgba per accent.
  const glow: Record<LatticePrefs['accent'], string> = {
    amber: 'rgba(251, 191, 36, 0.18)',
    violet: 'rgba(167, 139, 250, 0.18)',
    cyan: 'rgba(34, 211, 238, 0.18)',
    emerald: 'rgba(110, 231, 183, 0.18)',
  };
  root.style.setProperty('--accent-glow', glow[prefs.accent]);
  // Theme + density → dataset attributes on <html>. The reference
  // stylesheet's light-mode tweaks are scoped under `[data-theme="light"]`
  // (lattice.css:1278), so toggling a body class never matched. Dark is
  // the default with no attribute — we *delete* the attribute when the
  // theme isn't 'light' rather than setting it to '' (which would leave
  // a `data-theme=""` in the DOM and fail attribute-presence checks).
  if (prefs.theme === 'light') {
    root.dataset.theme = 'light';
  } else {
    delete root.dataset.theme;
  }
  if (prefs.density === 'compact') {
    root.dataset.density = 'compact';
  } else {
    delete root.dataset.density;
  }
}

// ─────────────────────────────────────────────────────────────────
// Error parsing — DRF returns { detail: "<field>: <reason>" } on 400.
// ─────────────────────────────────────────────────────────────────

interface ParsedError {
  field: keyof SettingsDict | null;
  message: string;
}

function parseSettingsError(err: unknown): ParsedError | null {
  if (!err) return null;
  if (!(err instanceof ApiError)) {
    return { field: null, message: err instanceof Error ? err.message : String(err) };
  }
  // Pull `detail` off the body if present, else fall back to the message.
  let raw: string = err.message;
  if (err.body && typeof err.body === 'object' && 'detail' in err.body) {
    const d = (err.body as { detail: unknown }).detail;
    if (typeof d === 'string') raw = d;
  }
  const idx = raw.indexOf(': ');
  if (idx === -1) return { field: null, message: raw };
  const fieldName = raw.slice(0, idx).trim();
  const message = raw.slice(idx + 2).trim();
  // Only flag as a field-error if the prefix is one we know about — keeps
  // weird server messages from being misrouted to a random input.
  const known: ReadonlyArray<keyof SettingsDict> = [
    'is_active', 'include_subdomains', 'max_depth', 'max_urls_per_session',
    'concurrency', 'request_delay', 'request_timeout', 'max_retries',
    'enable_js_rendering', 'respect_robots_txt', 'custom_user_agent',
    'excluded_paths', 'excluded_params',
  ];
  const matched = known.find((k) => k === fieldName);
  return matched
    ? { field: matched, message }
    : { field: null, message: raw };
}

// ─────────────────────────────────────────────────────────────────
// Diffing — only PATCH the fields the user actually changed.
// ─────────────────────────────────────────────────────────────────

const EDITABLE_KEYS: ReadonlyArray<keyof SettingsUpdate> = [
  'is_active', 'include_subdomains', 'max_depth', 'max_urls_per_session',
  'concurrency', 'request_delay', 'request_timeout', 'max_retries',
  'enable_js_rendering', 'respect_robots_txt', 'custom_user_agent',
  'excluded_paths', 'excluded_params',
];

// Keys that hold arrays — diffed by element-wise equality, not reference.
const ARRAY_KEYS: ReadonlySet<keyof SettingsUpdate> = new Set([
  'excluded_paths', 'excluded_params',
]);

function arraysEqual(a: readonly string[], b: readonly string[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function diffSettings(
  current: SettingsDict,
  base: SettingsDict,
): SettingsUpdate {
  const out: SettingsUpdate = {};
  for (const k of EDITABLE_KEYS) {
    let changed: boolean;
    if (ARRAY_KEYS.has(k)) {
      // Arrays compare by reference with !== so we'd otherwise PATCH on
      // every render. Element-wise compare keeps the diff honest.
      changed = !arraysEqual(
        current[k] as readonly string[],
        base[k] as readonly string[],
      );
    } else {
      changed = current[k] !== base[k];
    }
    if (changed) {
      // TS doesn't narrow the union mapping per-key here without acrobatics —
      // a single targeted cast keeps the runtime payload exact.
      (out as Record<string, unknown>)[k] = current[k];
    }
  }
  return out;
}

// Textarea <-> string[] helpers. Keeping textarea state as raw text (rather
// than re-deriving from form.excluded_paths.join('\n') on every keystroke)
// preserves the user's blank/trailing lines while typing — we only collapse
// to clean string[] at submit / diff time.
function parseLineList(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function formatLineList(items: readonly string[]): string {
  return items.join('\n');
}

// ─────────────────────────────────────────────────────────────────
// Shared inline styles for the textual <input>/<textarea> elements
// dropped into SettingRow.value slots. Centralising means a single
// place to tune surface/border/padding when the design tightens.
// ─────────────────────────────────────────────────────────────────

const INPUT_STYLE = {
  background: 'var(--surface)',
  color: 'var(--text-1)',
  border: '0.5px solid var(--border)',
  borderRadius: 6,
  padding: '6px 10px',
  fontFamily: 'inherit',
  fontSize: 12,
} as const;

const TEXTAREA_STYLE = {
  ...INPUT_STYLE,
  padding: '8px 10px',
  resize: 'vertical',
} as const;

// ─────────────────────────────────────────────────────────────────
// Page.
// ─────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { activeSiteId } = useActiveSite();
  const settingsQuery = useSettings(activeSiteId);
  const update = useUpdateSettings();

  // Local form state — initialised lazily from server data, re-synced
  // whenever the active site changes or the server payload refreshes
  // (e.g. after a successful PATCH the query is invalidated and the new
  // server-truth becomes the new "base").
  const [form, setForm] = useState<SettingsDict | null>(null);

  // Textarea raw text for the exclusion lists. Stored separately from
  // `form` so trailing newlines / blank-while-typing don't get eaten by
  // the parse/filter on every keystroke. We collapse to string[] when
  // mirroring into `form` (for diff/submit), but the textarea always
  // shows what the user actually typed.
  const [excludedPathsText, setExcludedPathsText] = useState('');
  const [excludedParamsText, setExcludedParamsText] = useState('');

  // Appearance prefs — client-only, persisted to localStorage. Lazy
  // initialiser pulls the saved value (or defaults) on first render
  // so the controls reflect persisted state immediately.
  const [prefs, setPrefs] = useState<LatticePrefs>(loadPrefs);

  // Apply on initial mount (once). Subsequent changes flow through
  // updatePrefs() which both writes localStorage and applies — so
  // we don't need a re-apply effect on every prefs change.
  useEffect(() => {
    applyPrefs(prefs);
    // One-shot — intentionally empty dep list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updatePrefs(patch: Partial<LatticePrefs>) {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      try {
        window.localStorage.setItem(LATTICE_PREFS_KEY, JSON.stringify(next));
      } catch {
        // localStorage may be unavailable (private mode / quota); the
        // in-memory state still updates so the UI stays consistent.
      }
      applyPrefs(next);
      return next;
    });
  }

  // Single source-of-truth sync effect.
  //
  // Previously this was split across two effects — one adopting
  // `settingsQuery.data` and one resetting on `activeSiteId` — which
  // raced when switching to a site whose data was already cached by
  // TanStack Query. Both effects fired in the same commit and the
  // reset won, leaving `form` stuck at null with no path back without
  // a remount. Collapsing into one effect keyed on both inputs makes
  // the order deterministic, and gating the adopt branch on the
  // server payload's website_id matching the active site keeps in-
  // flight responses for a previously-selected site from poisoning
  // the form when the user toggles fast.
  useEffect(() => {
    if (!settingsQuery.data) {
      // No data yet for this active site (initial fetch in flight,
      // or active site flipped to one we haven't loaded). Clear so
      // we don't render stale values from the previous site.
      setForm(null);
      setExcludedPathsText('');
      setExcludedParamsText('');
      update.reset();
      return;
    }
    if (settingsQuery.data.website_id === activeSiteId) {
      setForm(settingsQuery.data);
      setExcludedPathsText(formatLineList(settingsQuery.data.excluded_paths));
      setExcludedParamsText(formatLineList(settingsQuery.data.excluded_params));
      update.reset();
    }
    // `update` is a stable mutation object from TanStack Query (the
    // hook returns a fresh wrapper each render but `.reset` is bound
    // to a stable mutation); we deliberately exclude it to avoid an
    // effect-loop on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsQuery.data, activeSiteId]);

  const base = settingsQuery.data ?? null;
  const dirty = useMemo(() => {
    if (!form || !base) return {};
    return diffSettings(form, base);
  }, [form, base]);
  const hasChanges = Object.keys(dirty).length > 0;

  // Parsed textarea values — recomputed once per render rather than on
  // every keystroke. Used both for the count badges and the diff payload.
  const parsedExcludedPaths = useMemo(
    () => parseLineList(excludedPathsText),
    [excludedPathsText],
  );
  const parsedExcludedParams = useMemo(
    () => parseLineList(excludedParamsText),
    [excludedParamsText],
  );

  // Mirror parsed lists into `form` so diffSettings sees them. Effect (not
  // a derived render-time setForm) to avoid setState-during-render.
  useEffect(() => {
    setForm((prev) => {
      if (!prev) return prev;
      if (
        arraysEqual(prev.excluded_paths, parsedExcludedPaths)
        && arraysEqual(prev.excluded_params, parsedExcludedParams)
      ) {
        return prev;
      }
      return {
        ...prev,
        excluded_paths: parsedExcludedPaths,
        excluded_params: parsedExcludedParams,
      };
    });
  }, [parsedExcludedPaths, parsedExcludedParams]);

  const parsedError = parseSettingsError(update.error);
  const topLevelError = parsedError && parsedError.field === null
    ? parsedError.message
    : null;
  const fieldErr = (k: keyof SettingsDict): string | undefined =>
    parsedError?.field === k ? parsedError.message : undefined;

  function patchField<K extends keyof SettingsDict>(key: K, value: SettingsDict[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  function handleNumberChange(
    key: 'max_depth' | 'max_urls_per_session' | 'concurrency'
       | 'request_timeout' | 'max_retries',
  ) {
    return (e: ChangeEvent<HTMLInputElement>) => {
      // Empty string → 0 so the form stays controlled; the server still
      // range-validates so out-of-range entries surface a clear error.
      const v = e.target.value === '' ? 0 : Number(e.target.value);
      if (Number.isFinite(v)) patchField(key, Math.trunc(v));
    };
  }

  function handleFloatChange(e: ChangeEvent<HTMLInputElement>) {
    const v = e.target.value === '' ? 0 : Number(e.target.value);
    if (Number.isFinite(v)) patchField('request_delay', v);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form || !base || !activeSiteId || !hasChanges) return;
    update.mutate({ websiteId: activeSiteId, payload: dirty });
  }

  function handleDiscard() {
    if (base) {
      setForm(base);
      setExcludedPathsText(formatLineList(base.excluded_paths));
      setExcludedParamsText(formatLineList(base.excluded_params));
    }
    update.reset();
  }

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (settingsQuery.isPending) return 'Loading settings…';
    if (settingsQuery.isError) return 'Failed to load settings';
    if (!form) return 'Loading settings…';
    return hasChanges
      ? `${Object.keys(dirty).length} unsaved change${Object.keys(dirty).length === 1 ? '' : 's'}`
      : `Editing ${form.domain}`;
  })();

  // ── Right-hand value-slot builders ─────────────────────────────
  // Defined inline so they close over `form`/handlers without
  // shuttling props through. Each returns a ReactNode suitable for
  // the SettingRow `value` prop.
  const numberInput = (
    id: keyof SettingsDict,
    onChange: (e: ChangeEvent<HTMLInputElement>) => void,
    opts: { min?: number; max?: number; step?: number; width?: number } = {},
  ) => (
    <input
      id={id}
      type="number"
      value={form ? (form[id] as number) : 0}
      min={opts.min}
      max={opts.max}
      step={opts.step}
      onChange={onChange}
      aria-invalid={Boolean(fieldErr(id)) || undefined}
      style={{ ...INPUT_STYLE, width: opts.width ?? 180 }}
    />
  );

  return (
    // Wrapping the entire page-grid in <form> (rather than just the
    // editable card cluster) lets the 2-up `.settings-row` flow include
    // non-form cards (Schedule, API & integrations, Appearance) without
    // breaking the grid pairing. All "Coming soon" buttons are
    // type="button" so they don't accidentally submit, and the toggle
    // pills render as type="button" too.
    <form
      onSubmit={handleSubmit}
      className="page-grid"
      // The fixed save bar sits 56px tall at bottom-right; keep the page
      // bottom-padded so the last card never hides under it.
      style={{ paddingBottom: 72 }}
    >
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <div className="page-subtitle">{subtitle}</div>
        </div>
      </div>

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to configure its crawl settings.
          </p>
        </div>
      )}

      {activeSiteId && settingsQuery.isError && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p style={{ color: 'var(--error, #f87171)' }}>
            Failed to load settings
            {settingsQuery.error instanceof Error
              ? `: ${settingsQuery.error.message}`
              : '.'}
          </p>
        </div>
      )}

      {activeSiteId && settingsQuery.isPending && !form && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">Loading settings…</p>
        </div>
      )}

      {activeSiteId && form && base && (
        <>
          {/* ── Identity (full-width) ─────────────────────────── */}
          <section className="card settings-card">
            <h3>Identity</h3>
            <SettingRow label="Domain" value={form.domain} />
            <SettingRow label="Website ID" value={form.website_id} mono />
          </section>

          {/* ── Crawl behaviour | Crawl scope ─────────────────── */}
          <div className="row settings-row">
            <section className="card settings-card">
              <h3>Crawl behaviour</h3>
              <SettingRow
                label="Active"
                hint="Inactive sites are skipped by scheduled crawls."
                toggle={{
                  checked: form.is_active,
                  onChange: (v) => patchField('is_active', v),
                  ariaLabel: 'Active',
                }}
                error={fieldErr('is_active')}
              />
              <SettingRow
                label="Include subdomains"
                hint="Follow links to other subdomains of the same registered domain."
                toggle={{
                  checked: form.include_subdomains,
                  onChange: (v) => patchField('include_subdomains', v),
                  ariaLabel: 'Include subdomains',
                }}
                error={fieldErr('include_subdomains')}
              />
              <SettingRow
                label="JavaScript rendering"
                hint="Render pages in a headless browser before extracting links."
                toggle={{
                  checked: form.enable_js_rendering,
                  onChange: (v) => patchField('enable_js_rendering', v),
                  ariaLabel: 'JavaScript rendering',
                }}
                error={fieldErr('enable_js_rendering')}
              />
              <SettingRow
                label="Respect robots.txt"
                hint="Skip URLs disallowed by the site's robots.txt."
                toggle={{
                  checked: form.respect_robots_txt,
                  onChange: (v) => patchField('respect_robots_txt', v),
                  ariaLabel: 'Respect robots.txt',
                }}
                error={fieldErr('respect_robots_txt')}
              />
            </section>

            <section className="card settings-card">
              <h3>Crawl scope</h3>
              <SettingRow
                label="Max depth"
                hint="0–50. How many link-hops deep the crawler will follow."
                value={numberInput('max_depth', handleNumberChange('max_depth'), {
                  min: 0, max: 50,
                })}
                error={fieldErr('max_depth')}
              />
              <SettingRow
                label="Max URLs per session"
                hint="1–1,000,000. Hard cap on total URLs visited per crawl."
                value={numberInput(
                  'max_urls_per_session',
                  handleNumberChange('max_urls_per_session'),
                  { min: 1, max: 1_000_000 },
                )}
                error={fieldErr('max_urls_per_session')}
              />
              <SettingRow
                label="Concurrency"
                hint="1–100. Number of parallel fetcher workers."
                value={numberInput('concurrency', handleNumberChange('concurrency'), {
                  min: 1, max: 100,
                })}
                error={fieldErr('concurrency')}
              />
            </section>
          </div>

          {/* ── Networking | User agent ───────────────────────── */}
          <div className="row settings-row">
            <section className="card settings-card">
              <h3>Networking</h3>
              <SettingRow
                label="Request delay (s)"
                hint="0.0–60.0. Pause between requests; useful for polite crawls."
                value={numberInput('request_delay', handleFloatChange, {
                  min: 0, max: 60, step: 0.1,
                })}
                error={fieldErr('request_delay')}
              />
              <SettingRow
                label="Request timeout (s)"
                hint="1–300. Per-URL HTTP timeout before the request is abandoned."
                value={numberInput(
                  'request_timeout',
                  handleNumberChange('request_timeout'),
                  { min: 1, max: 300 },
                )}
                error={fieldErr('request_timeout')}
              />
              <SettingRow
                label="Max retries"
                hint="0–10. Number of retry attempts on transient failures."
                value={numberInput('max_retries', handleNumberChange('max_retries'), {
                  min: 0, max: 10,
                })}
                error={fieldErr('max_retries')}
              />
            </section>

            <section className="card settings-card">
              <h3>User agent</h3>
              <SettingRow
                label="Custom UA"
                hint={`${form.custom_user_agent.length}/500 chars. Leave blank to use the default crawler UA.`}
                value={(
                  <textarea
                    id="custom_user_agent"
                    value={form.custom_user_agent}
                    onChange={(e) =>
                      patchField('custom_user_agent', e.target.value)
                    }
                    maxLength={500}
                    rows={3}
                    aria-invalid={
                      parsedError?.field === 'custom_user_agent' || undefined
                    }
                    style={{ ...TEXTAREA_STYLE, width: '100%' }}
                  />
                )}
                error={fieldErr('custom_user_agent')}
              />
            </section>
          </div>

          {/* ── Excluded paths/params | Schedule (coming soon) ─ */}
          <div className="row settings-row">
            <section className="card settings-card">
              <h3>Inclusions / exclusions</h3>
              <SettingRow
                label="Excluded paths"
                hint='URL path prefixes to skip. One per line, e.g. "/admin" or "/private". Storage only — engine enforcement is a follow-up.'
                badge={
                  parsedExcludedPaths.length === 1
                    ? '1 path'
                    : `${parsedExcludedPaths.length} paths`
                }
                value={(
                  <textarea
                    id="excluded_paths"
                    value={excludedPathsText}
                    onChange={(e) => setExcludedPathsText(e.target.value)}
                    rows={5}
                    spellCheck={false}
                    aria-invalid={
                      parsedError?.field === 'excluded_paths' || undefined
                    }
                    style={{
                      ...TEXTAREA_STYLE,
                      width: '100%',
                      minHeight: 96,
                      fontFamily:
                        'var(--font-mono, ui-monospace, monospace)',
                    }}
                  />
                )}
                error={fieldErr('excluded_paths')}
              />
              <SettingRow
                label="Excluded params"
                hint='Query-string keys to strip before deduplication. One per line, e.g. "utm_source" or "fbclid".'
                badge={
                  parsedExcludedParams.length === 1
                    ? '1 param'
                    : `${parsedExcludedParams.length} params`
                }
                value={(
                  <textarea
                    id="excluded_params"
                    value={excludedParamsText}
                    onChange={(e) => setExcludedParamsText(e.target.value)}
                    rows={5}
                    spellCheck={false}
                    aria-invalid={
                      parsedError?.field === 'excluded_params' || undefined
                    }
                    style={{
                      ...TEXTAREA_STYLE,
                      width: '100%',
                      minHeight: 96,
                      fontFamily:
                        'var(--font-mono, ui-monospace, monospace)',
                    }}
                  />
                )}
                error={fieldErr('excluded_params')}
              />
            </section>

            {/* Schedule — coming-soon panel paired with the
                exclusions card so the 2-up grid stays balanced. */}
            <section
              className="card settings-card coming-soon"
              aria-disabled="true"
              style={{ opacity: 0.6 }}
            >
              <h3>Crawl schedule</h3>
              <SettingRow
                label="Cron"
                value={<span className="mono">0 * * * *</span>}
                hint="Scheduled crawls (Celery beat) are not enabled in v1."
              />
              <SettingRow
                label="Timezone"
                value="UTC"
              />
              <SettingRow
                label="Status"
                value={(
                  <button type="button" className="btn ghost" disabled>
                    Coming soon
                  </button>
                )}
                off
              />
            </section>
          </div>

          {topLevelError && (
            <div
              role="alert"
              className="card"
              style={{
                padding: '10px var(--pad)',
                color: 'var(--error, #f87171)',
                fontSize: 12,
              }}
            >
              {topLevelError}
            </div>
          )}
        </>
      )}

      {/* ── Appearance | API & integrations ─────────────────────────
          Renders regardless of active-site selection — Appearance is
          user-scoped (localStorage), and the API integrations panel
          is informational. Pairing them keeps the 2-up grid balanced
          on the bottom row of the page. */}
      <div className="row settings-row">
        <section className="card settings-card">
          <h3>Appearance</h3>
          <SettingRow
            label="Accent"
            hint="Primary highlight colour across the UI."
            value={(
              <SegmentedControl<LatticePrefs['accent']>
                ariaLabel="Accent"
                value={prefs.accent}
                options={[
                  { value: 'emerald', label: 'Emerald' },
                  { value: 'amber', label: 'Amber' },
                  { value: 'violet', label: 'Violet' },
                  { value: 'cyan', label: 'Cyan' },
                ]}
                swatch={(v) => ACCENT_HEX[v]}
                onChange={(v) => updatePrefs({ accent: v })}
              />
            )}
          />
          <SettingRow
            label="Density"
            hint="Comfortable for browsing, compact for dense data tables."
            value={(
              <SegmentedControl<LatticePrefs['density']>
                ariaLabel="Density"
                value={prefs.density}
                options={[
                  { value: 'comfortable', label: 'Comfortable' },
                  { value: 'compact', label: 'Compact' },
                ]}
                onChange={(v) => updatePrefs({ density: v })}
              />
            )}
          />
          <SettingRow
            label="Theme"
            hint="System follows your OS-level light/dark setting."
            value={(
              <SegmentedControl<LatticePrefs['theme']>
                ariaLabel="Theme"
                value={prefs.theme}
                options={[
                  { value: 'dark', label: 'Dark' },
                  { value: 'light', label: 'Light' },
                  { value: 'system', label: 'System' },
                ]}
                onChange={(v) => updatePrefs({ theme: v })}
              />
            )}
          />
          <SettingRow
            label="Storage"
            hint="Stored in your browser only — no backend round-trip."
            value={<span className="text-muted">localStorage</span>}
          />
        </section>

        <section
          className="card settings-card coming-soon"
          aria-disabled="true"
          style={{ opacity: 0.6 }}
        >
          <h3>API &amp; integrations</h3>
          <SettingRow
            label="Slack"
            value={(
              <button type="button" className="btn ghost" disabled>
                Connect Slack
              </button>
            )}
            off
          />
          <SettingRow
            label="GA4"
            value={(
              <button type="button" className="btn ghost" disabled>
                Link GA4 property
              </button>
            )}
            off
          />
          <SettingRow
            label="Webhooks"
            value={(
              <button type="button" className="btn ghost" disabled>
                Add webhook
              </button>
            )}
            off
          />
          <SettingRow
            label="Status"
            hint="Slack, GA4, and webhook integrations are out-of-scope for v1."
            value={<span className="text-muted">Coming soon</span>}
          />
        </section>
      </div>

      {/* ── Save bar (fixed) ──────────────────────────────────────
          Pinned to bottom-right of the viewport with a high
          z-index so it floats over scrolling content on long
          settings pages. Only renders when there's something to
          save — keeps the chrome clean for read-only / loading
          states. */}
      {activeSiteId && form && base && (
        <div
          className="card"
          style={{
            position: 'fixed',
            right: 16,
            bottom: 16,
            zIndex: 50,
            padding: '8px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            boxShadow: '0 6px 20px rgba(0, 0, 0, 0.35)',
          }}
        >
          {hasChanges && !update.isPending && (
            <span className="text-muted" style={{ fontSize: 11 }}>
              {Object.keys(dirty).length} unsaved change
              {Object.keys(dirty).length === 1 ? '' : 's'}
            </span>
          )}
          <button
            type="button"
            className="btn ghost"
            onClick={handleDiscard}
            disabled={!hasChanges || update.isPending}
          >
            Discard
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={!hasChanges || update.isPending}
          >
            {update.isPending ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      )}
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────
// SegmentedControl — buttons-only segmented input. Lives in
// SettingRow.value rather than owning its own row grid (the prior
// SegmentedRow nested a 180px/1fr grid inside the parent setting-row,
// which made the column widths fight). Each option is a button with
// an optional colour swatch (for the accent picker).
// ─────────────────────────────────────────────────────────────────

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  value: T;
  options: ReadonlyArray<SegmentedOption<T>>;
  onChange: (v: T) => void;
  swatch?: (v: T) => string;
  ariaLabel?: string;
}

function SegmentedControl<T extends string>({
  value, options, onChange, swatch, ariaLabel,
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: active ? 'var(--accent-glow)' : 'var(--surface)',
              color: active ? 'var(--accent)' : 'var(--text-1)',
              border: `0.5px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 6,
              padding: '5px 10px',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            {swatch && (
              <span
                aria-hidden
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: swatch(opt.value),
                  boxShadow: '0 0 0 0.5px rgba(0, 0, 0, 0.25)',
                }}
              />
            )}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
