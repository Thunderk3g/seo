// client.ts — minimal fetch wrapper for the Lattice API.
// No real calls happen yet; TanStack Query hooks (Day 1+) will use this.

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

const API_BASE = '/api/v1';

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  // JSON-serialisable body. Use raw fetch + RequestInit if you need streaming.
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const base = path.startsWith('http') ? path : `${API_BASE}${path}`;
  if (!query) return base;
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    usp.set(k, String(v));
  }
  const qs = usp.toString();
  return qs ? `${base}?${qs}` : base;
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: RequestOptions = {}
): Promise<T> {
  const { body, query, headers, ...rest } = opts;
  const init: RequestInit = {
    ...rest,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
  };
  if (body !== undefined) {
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
  }

  const url = buildUrl(path, query);
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    throw new ApiError(
      `Network error contacting ${url}: ${(err as Error).message}`,
      0,
      null
    );
  }

  const contentType = res.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const payload = isJson
    ? await res.json().catch(() => null)
    : await res.text().catch(() => null);

  if (!res.ok) {
    const message =
      (isJson && payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : null) || `Request to ${url} failed with ${res.status}`;
    throw new ApiError(message, res.status, payload);
  }

  return payload as T;
}

export const api = {
  get: <T,>(path: string, query?: RequestOptions['query']) =>
    apiFetch<T>(path, { method: 'GET', query }),
  post: <T,>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'POST', body }),
  patch: <T,>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: 'PATCH', body }),
  delete: <T,>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
};
