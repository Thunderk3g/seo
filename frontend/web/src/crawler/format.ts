// Formatting helpers for the embedded Crawler Engine pages.
// Ported from Crawler_v2.0.0/frontend/src/utils/format.js.

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString();
}

export function fmtDuration(sec: number | null | undefined): string {
  if (!sec || sec < 0) return '0s';
  let s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  s = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

export function fmtTime(ts: string | number | null | undefined): string {
  if (!ts) return '--:--:--';
  const d = new Date(ts);
  return d.toTimeString().slice(0, 8);
}

export type BadgeTone = 'ok' | 'err' | 'warn' | 'info' | 'muted';

export function statusBadge(code: string | number | null | undefined): BadgeTone {
  const n = Number(code);
  if (!n) return 'muted';
  if (n >= 200 && n < 300) return 'ok';
  if (n >= 300 && n < 400) return 'info';
  if (n === 404) return 'err';
  if (n >= 400 && n < 500) return 'warn';
  if (n >= 500) return 'err';
  return 'muted';
}
