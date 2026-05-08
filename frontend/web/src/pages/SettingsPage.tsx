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

import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { ApiError } from '../api/client';
import { useActiveSite } from '../api/hooks/useActiveSite';
import {
  useSettings,
  useUpdateSettings,
} from '../api/hooks/useSettings';
import type { LatticePrefs, SettingsDict, SettingsUpdate } from '../api/types';

// ─────────────────────────────────────────────────────────────────
// Appearance preferences (spec §5.4.8/§5.4.9). Client-only — stored
// in localStorage under `lattice.prefs`, applied to <html>/<body>
// via a CSS variable (--accent) plus density/theme body classes.
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
  // Accent → CSS custom property on <html>. Glow/hover variants stay
  // baked-in (lattice.css uses --accent-glow, --accent-hover); we
  // recompute those here so the whole UI tracks the new accent.
  const hex = ACCENT_HEX[prefs.accent];
  document.documentElement.style.setProperty('--accent', hex);
  document.documentElement.style.setProperty('--accent-hover', hex);
  // accent-glow = same hex at ~18% alpha; pre-baked rgba per accent.
  const glow: Record<LatticePrefs['accent'], string> = {
    amber: 'rgba(251, 191, 36, 0.18)',
    violet: 'rgba(167, 139, 250, 0.18)',
    cyan: 'rgba(34, 211, 238, 0.18)',
    emerald: 'rgba(110, 231, 183, 0.18)',
  };
  document.documentElement.style.setProperty('--accent-glow', glow[prefs.accent]);
  // Density + theme → body classes (toggled, not appended).
  const body = document.body;
  body.classList.toggle('density-compact', prefs.density === 'compact');
  body.classList.toggle('density-comfortable', prefs.density === 'comfortable');
  body.classList.toggle('theme-light', prefs.theme === 'light');
  // 'system' and 'dark' both leave the .theme-light class off; the
  // base stylesheet is dark and 'system' inherits OS-level prefs via
  // existing media queries (if any) on the host page.
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
// Inline error helper.
// ─────────────────────────────────────────────────────────────────

function FieldError({ message }: { message: string | undefined }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      style={{
        color: 'var(--error, #f87171)',
        fontSize: 11,
        marginTop: 4,
        paddingLeft: 4,
      }}
    >
      {message}
    </div>
  );
}

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

  return (
    <div className="page-grid">
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
        <form
          onSubmit={handleSubmit}
          style={{ display: 'flex', flexDirection: 'column', gap: 14 }}
        >
          {/* ── Identity ─────────────────────────────────────────────── */}
          <section className="card" style={{ padding: 'var(--pad)' }}>
            <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
              <h3>Identity</h3>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <ReadOnlyRow label="Domain" value={form.domain} />
              <ReadOnlyRow label="Website ID" value={form.website_id} mono small />
            </div>
          </section>

          {/* ── Crawl behaviour ──────────────────────────────────────── */}
          <section className="card" style={{ padding: 'var(--pad)' }}>
            <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
              <h3>Crawl behaviour</h3>
            </div>
            <div style={{ display: 'grid', gap: 8 }}>
              <ToggleRow
                id="is_active"
                label="Active"
                hint="Inactive sites are skipped by scheduled crawls."
                checked={form.is_active}
                onChange={(v) => patchField('is_active', v)}
                error={parsedError?.field === 'is_active' ? parsedError.message : undefined}
              />
              <ToggleRow
                id="include_subdomains"
                label="Include subdomains"
                hint="Follow links to other subdomains of the same registered domain."
                checked={form.include_subdomains}
                onChange={(v) => patchField('include_subdomains', v)}
                error={parsedError?.field === 'include_subdomains' ? parsedError.message : undefined}
              />
              <ToggleRow
                id="enable_js_rendering"
                label="JavaScript rendering"
                hint="Render pages in a headless browser before extracting links."
                checked={form.enable_js_rendering}
                onChange={(v) => patchField('enable_js_rendering', v)}
                error={parsedError?.field === 'enable_js_rendering' ? parsedError.message : undefined}
              />
              <ToggleRow
                id="respect_robots_txt"
                label="Respect robots.txt"
                hint="Skip URLs disallowed by the site's robots.txt."
                checked={form.respect_robots_txt}
                onChange={(v) => patchField('respect_robots_txt', v)}
                error={parsedError?.field === 'respect_robots_txt' ? parsedError.message : undefined}
              />
            </div>
          </section>

          {/* ── Crawl scope ──────────────────────────────────────────── */}
          <section className="card" style={{ padding: 'var(--pad)' }}>
            <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
              <h3>Crawl scope</h3>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <NumberRow
                id="max_depth"
                label="Max depth"
                hint="0–50. How many link-hops deep the crawler will follow."
                value={form.max_depth}
                min={0}
                max={50}
                onChange={handleNumberChange('max_depth')}
                error={parsedError?.field === 'max_depth' ? parsedError.message : undefined}
              />
              <NumberRow
                id="max_urls_per_session"
                label="Max URLs per session"
                hint="1–1,000,000. Hard cap on total URLs visited per crawl."
                value={form.max_urls_per_session}
                min={1}
                max={1_000_000}
                onChange={handleNumberChange('max_urls_per_session')}
                error={parsedError?.field === 'max_urls_per_session' ? parsedError.message : undefined}
              />
              <NumberRow
                id="concurrency"
                label="Concurrency"
                hint="1–100. Number of parallel fetcher workers."
                value={form.concurrency}
                min={1}
                max={100}
                onChange={handleNumberChange('concurrency')}
                error={parsedError?.field === 'concurrency' ? parsedError.message : undefined}
              />
            </div>
          </section>

          {/* ── Networking ───────────────────────────────────────────── */}
          <section className="card" style={{ padding: 'var(--pad)' }}>
            <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
              <h3>Networking</h3>
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <NumberRow
                id="request_delay"
                label="Request delay (s)"
                hint="0.0–60.0. Pause between requests; useful for polite crawls."
                value={form.request_delay}
                min={0}
                max={60}
                step={0.1}
                onChange={handleFloatChange}
                error={parsedError?.field === 'request_delay' ? parsedError.message : undefined}
              />
              <NumberRow
                id="request_timeout"
                label="Request timeout (s)"
                hint="1–300. Per-URL HTTP timeout before the request is abandoned."
                value={form.request_timeout}
                min={1}
                max={300}
                onChange={handleNumberChange('request_timeout')}
                error={parsedError?.field === 'request_timeout' ? parsedError.message : undefined}
              />
              <NumberRow
                id="max_retries"
                label="Max retries"
                hint="0–10. Number of retry attempts on transient failures."
                value={form.max_retries}
                min={0}
                max={10}
                onChange={handleNumberChange('max_retries')}
                error={parsedError?.field === 'max_retries' ? parsedError.message : undefined}
              />
            </div>
          </section>

          {/* ── User agent ───────────────────────────────────────────── */}
          <section className="card" style={{ padding: 'var(--pad)' }}>
            <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
              <h3>User agent</h3>
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              <label htmlFor="custom_user_agent" style={{ fontSize: 12 }}>
                Custom user-agent string
              </label>
              <textarea
                id="custom_user_agent"
                value={form.custom_user_agent}
                onChange={(e) => patchField('custom_user_agent', e.target.value)}
                maxLength={500}
                rows={2}
                aria-invalid={parsedError?.field === 'custom_user_agent' || undefined}
                style={{
                  background: 'var(--surface)',
                  color: 'var(--text-1)',
                  border: '0.5px solid var(--border)',
                  borderRadius: 6,
                  padding: '8px 10px',
                  fontFamily: 'inherit',
                  fontSize: 12,
                  resize: 'vertical',
                }}
              />
              <div className="text-muted" style={{ fontSize: 11 }}>
                {form.custom_user_agent.length}/500 chars. Leave blank to use the
                default crawler UA.
              </div>
              <FieldError
                message={
                  parsedError?.field === 'custom_user_agent'
                    ? parsedError.message
                    : undefined
                }
              />
            </div>
          </section>

          {/* ── Excluded paths & params (spec §5.4.8) ────────────────── */}
          {/* Storage only — engine enforcement is a follow-up. Each non-
              empty line becomes one entry; the server caps at 100 entries
              and 200 chars per entry. */}
          <section className="card" style={{ padding: 'var(--pad)' }}>
            <div
              className="card-head"
              style={{
                padding: 0,
                marginBottom: 10,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                gap: 12,
              }}
            >
              <h3>Excluded paths &amp; params</h3>
              <span className="text-muted" style={{ fontSize: 11 }}>
                {parsedExcludedPaths.length}{' '}
                {parsedExcludedPaths.length === 1 ? 'path' : 'paths'}
                {' · '}
                {parsedExcludedParams.length}{' '}
                {parsedExcludedParams.length === 1 ? 'param' : 'params'}
              </span>
            </div>
            <div style={{ display: 'grid', gap: 14 }}>
              <LineListField
                id="excluded_paths"
                label="Excluded paths"
                hint='URL path prefixes to skip. One per line, e.g. "/admin" or "/private". Storage only — engine enforcement is a follow-up.'
                value={excludedPathsText}
                count={parsedExcludedPaths.length}
                countLabel={parsedExcludedPaths.length === 1 ? 'path' : 'paths'}
                onChange={(e) => setExcludedPathsText(e.target.value)}
                error={
                  parsedError?.field === 'excluded_paths'
                    ? parsedError.message
                    : undefined
                }
              />
              <LineListField
                id="excluded_params"
                label="Excluded query params"
                hint='Query-string keys to strip before deduplication. One per line, e.g. "utm_source" or "fbclid".'
                value={excludedParamsText}
                count={parsedExcludedParams.length}
                countLabel={parsedExcludedParams.length === 1 ? 'param' : 'params'}
                onChange={(e) => setExcludedParamsText(e.target.value)}
                error={
                  parsedError?.field === 'excluded_params'
                    ? parsedError.message
                    : undefined
                }
              />
            </div>
          </section>

          {/* ── Action bar ───────────────────────────────────────────── */}
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

          <div
            style={{
              display: 'flex',
              gap: 8,
              justifyContent: 'flex-end',
              alignItems: 'center',
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
        </form>
      )}

      {/* ── Appearance (spec §5.4.8 + §5.4.9) ──────────────────────────
          Client-only prefs persisted to localStorage under
          `lattice.prefs`. Renders regardless of active-site selection
          since these are user-scoped, not site-scoped. */}
      <section className="card" style={{ padding: 'var(--pad)' }}>
        <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
          <h3>Appearance</h3>
        </div>
        <div className="text-muted" style={{ fontSize: 11, marginBottom: 12 }}>
          Stored in your browser only — no backend round-trip.
        </div>
        <div style={{ display: 'grid', gap: 14 }}>
          <SegmentedRow<LatticePrefs['accent']>
            label="Accent"
            hint="Primary highlight colour across the UI."
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
          <SegmentedRow<LatticePrefs['density']>
            label="Density"
            hint="Comfortable for browsing, compact for dense data tables."
            value={prefs.density}
            options={[
              { value: 'comfortable', label: 'Comfortable' },
              { value: 'compact', label: 'Compact' },
            ]}
            onChange={(v) => updatePrefs({ density: v })}
          />
          <SegmentedRow<LatticePrefs['theme']>
            label="Theme"
            hint="System follows your OS-level light/dark setting."
            value={prefs.theme}
            options={[
              { value: 'dark', label: 'Dark' },
              { value: 'light', label: 'Light' },
              { value: 'system', label: 'System' },
            ]}
            onChange={(v) => updatePrefs({ theme: v })}
          />
        </div>
      </section>

      {/* ── Crawl schedule (coming soon — spec §5.4.8) ─────────────────
          Spec calls for a visually-consistent informational panel;
          Celery beat is out of scope for v1. */}
      <section
        className="card coming-soon"
        style={{ padding: 'var(--pad)', opacity: 0.6 }}
        aria-disabled="true"
      >
        <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
          <h3>Crawl schedule</h3>
        </div>
        <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>
          Scheduled crawls (Celery beat) are not enabled in v1. Trigger manual
          crawls from the topbar.
        </p>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(5, max-content)',
            gap: 8,
            alignItems: 'center',
            pointerEvents: 'none',
          }}
        >
          <span className="text-muted" style={{ fontSize: 11 }}>Cron</span>
          <input
            type="text"
            value="0 * * * *"
            readOnly
            disabled
            aria-label="Cron expression (disabled)"
            style={{
              background: 'var(--surface)',
              color: 'var(--text-1)',
              border: '0.5px solid var(--border)',
              borderRadius: 6,
              padding: '6px 10px',
              fontFamily: 'var(--font-mono, ui-monospace, monospace)',
              fontSize: 12,
              width: 140,
            }}
          />
          <span className="text-muted" style={{ fontSize: 11 }}>Timezone</span>
          <input
            type="text"
            value="UTC"
            readOnly
            disabled
            aria-label="Timezone (disabled)"
            style={{
              background: 'var(--surface)',
              color: 'var(--text-1)',
              border: '0.5px solid var(--border)',
              borderRadius: 6,
              padding: '6px 10px',
              fontSize: 12,
              width: 80,
            }}
          />
          <button type="button" className="btn ghost" disabled>
            Coming soon
          </button>
        </div>
      </section>

      {/* ── API & integrations (coming soon — spec §5.4.8) ─────────── */}
      <section
        className="card coming-soon"
        style={{ padding: 'var(--pad)', opacity: 0.6 }}
        aria-disabled="true"
      >
        <div className="card-head" style={{ padding: 0, marginBottom: 10 }}>
          <h3>API &amp; integrations</h3>
        </div>
        <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>
          Slack, GA4, and webhook integrations are out-of-scope for v1.
        </p>
        <div
          style={{
            display: 'flex',
            gap: 8,
            flexWrap: 'wrap',
            pointerEvents: 'none',
          }}
        >
          <button type="button" className="btn ghost" disabled>
            Connect Slack
          </button>
          <button type="button" className="btn ghost" disabled>
            Link GA4 property
          </button>
          <button type="button" className="btn ghost" disabled>
            Add webhook
          </button>
        </div>
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Small row primitives — keeps the page body readable.
// ─────────────────────────────────────────────────────────────────

interface ReadOnlyRowProps {
  label: string;
  value: string;
  mono?: boolean;
  small?: boolean;
}

function ReadOnlyRow({ label, value, mono, small }: ReadOnlyRowProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <div style={{ fontSize: 12 }}>{label}</div>
      <div
        className="text-muted"
        style={{
          fontFamily: mono ? 'var(--font-mono, ui-monospace, monospace)' : undefined,
          fontSize: small ? 11 : 12,
          wordBreak: 'break-all',
        }}
      >
        {value}
      </div>
    </div>
  );
}

interface ToggleRowProps {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  error?: string;
}

function ToggleRow({ id, label, hint, checked, onChange, error }: ToggleRowProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr auto',
        alignItems: 'start',
        gap: 12,
        paddingTop: 6,
        paddingBottom: 6,
        borderTop: '0.5px dashed var(--border)',
      }}
    >
      <label htmlFor={id} style={{ fontSize: 12, paddingTop: 2 }}>
        {label}
      </label>
      <div>
        <div className="text-muted" style={{ fontSize: 11 }}>{hint}</div>
        <FieldError message={error} />
      </div>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-invalid={Boolean(error) || undefined}
      />
    </div>
  );
}

interface LineListFieldProps {
  id: string;
  label: string;
  hint: string;
  value: string;
  count: number;
  countLabel: string;
  onChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  error?: string;
}

function LineListField({
  id, label, hint, value, count, countLabel, onChange, error,
}: LineListFieldProps) {
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          gap: 12,
        }}
      >
        <label htmlFor={id} style={{ fontSize: 12 }}>
          {label}
        </label>
        <span className="text-muted" style={{ fontSize: 11 }}>
          {count} {countLabel}
        </span>
      </div>
      <textarea
        id={id}
        value={value}
        onChange={onChange}
        rows={5}
        spellCheck={false}
        aria-invalid={Boolean(error) || undefined}
        style={{
          background: 'var(--surface)',
          color: 'var(--text-1)',
          border: '0.5px solid var(--border)',
          borderRadius: 6,
          padding: '8px 10px',
          fontFamily: 'var(--font-mono, ui-monospace, monospace)',
          fontSize: 12,
          resize: 'vertical',
          minHeight: 96,
        }}
      />
      <div className="text-muted" style={{ fontSize: 11 }}>
        {hint}
      </div>
      <FieldError message={error} />
    </div>
  );
}

interface NumberRowProps {
  id: string;
  label: string;
  hint: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (e: ChangeEvent<HTMLInputElement>) => void;
  error?: string;
}

function NumberRow({
  id, label, hint, value, min, max, step, onChange, error,
}: NumberRowProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr',
        alignItems: 'start',
        gap: 12,
        paddingTop: 6,
        paddingBottom: 6,
        borderTop: '0.5px dashed var(--border)',
      }}
    >
      <label htmlFor={id} style={{ fontSize: 12, paddingTop: 6 }}>
        {label}
      </label>
      <div>
        <input
          id={id}
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={onChange}
          aria-invalid={Boolean(error) || undefined}
          style={{
            background: 'var(--surface)',
            color: 'var(--text-1)',
            border: '0.5px solid var(--border)',
            borderRadius: 6,
            padding: '6px 10px',
            width: 180,
            fontFamily: 'inherit',
            fontSize: 12,
          }}
        />
        <div className="text-muted" style={{ fontSize: 11, marginTop: 4 }}>
          {hint}
        </div>
        <FieldError message={error} />
      </div>
    </div>
  );
}

// Generic segmented control — used by the Appearance card. Each option
// renders as a button that visually highlights when active. Optional
// `swatch` paints a small colour dot (used by the accent picker).
interface SegmentedRowOption<T extends string> {
  value: T;
  label: string;
}
interface SegmentedRowProps<T extends string> {
  label: string;
  hint: string;
  value: T;
  options: ReadonlyArray<SegmentedRowOption<T>>;
  swatch?: (v: T) => string;
  onChange: (v: T) => void;
}

function SegmentedRow<T extends string>({
  label, hint, value, options, swatch, onChange,
}: SegmentedRowProps<T>) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr',
        alignItems: 'start',
        gap: 12,
        paddingTop: 6,
        paddingBottom: 6,
        borderTop: '0.5px dashed var(--border)',
      }}
    >
      <div style={{ fontSize: 12, paddingTop: 6 }}>{label}</div>
      <div>
        <div
          role="radiogroup"
          aria-label={label}
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
        <div className="text-muted" style={{ fontSize: 11, marginTop: 4 }}>
          {hint}
        </div>
      </div>
    </div>
  );
}
