import { API_PREFIX, REQUEST_TIMEOUT_MS } from '@/lib/config';

import { clearSession, currentSession, saveSession, type Session } from './tokenStore';
import type { StatusCode, TokenPair } from './types';

export class ApiError extends Error {
  constructor(
    public readonly code: StatusCode,
    message: string,
    public readonly httpStatus: number,
    public readonly details: Record<string, any> = {},
    public readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get isNetwork(): boolean {
    return this.code === 'NETWORK_ERROR' || this.code === 'TIMEOUT';
  }
}

type Listener = () => void;
let onSessionExpired: Listener | null = null;
export function setSessionExpiredHandler(fn: Listener | null): void {
  onSessionExpired = fn;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  auth?: boolean;
  timeoutMs?: number;
  /** Return the parsed body for any HTTP status that carries an application `status` (search envelopes). */
  envelope?: boolean;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const qs = Object.entries(query ?? {})
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
  return `${API_PREFIX}${path}${qs ? `?${qs}` : ''}`;
}

async function rawFetch(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } catch (e: any) {
    if (e?.name === 'AbortError') throw new ApiError('TIMEOUT', 'The server took too long to respond.', 0);
    throw new ApiError('NETWORK_ERROR', 'Cannot reach the server. Check your connection.', 0);
  } finally {
    clearTimeout(timer);
  }
}

let refreshing: Promise<Session | null> | null = null;

/** Single-flight refresh: concurrent 401s share one refresh request (refresh tokens rotate). */
export function refreshSession(): Promise<Session | null> {
  if (refreshing) return refreshing;
  const s = currentSession();
  if (!s) return Promise.resolve(null);
  refreshing = (async () => {
    try {
      const res = await rawFetch(
        buildUrl('/auth/refresh'),
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: s.refreshToken }) },
        REQUEST_TIMEOUT_MS,
      );
      if (!res.ok) {
        if (res.status === 401) {
          await clearSession();
          onSessionExpired?.();
        }
        return null;
      }
      const t = (await res.json()) as TokenPair;
      const next = { accessToken: t.access_token, refreshToken: t.refresh_token, accessExpiresAt: t.access_expires_at };
      await saveSession(next);
      return next;
    } catch {
      return null; // network problem: keep the session; caller surfaces the network error
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function request<T = any>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, form, query, auth = true, timeoutMs = REQUEST_TIMEOUT_MS, envelope = false } = opts;

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const s = currentSession();
    if (auth && s) headers.Authorization = `Bearer ${s.accessToken}`;
    return rawFetch(buildUrl(path, query), { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) }, timeoutMs);
  };

  let res = await send();
  if (res.status === 401 && auth && currentSession()) {
    const peek = await res.clone().json().catch(() => ({}));
    const reason = peek?.details?.reason;
    if (reason === 'TOKEN_EXPIRED' || reason === 'TOKEN_INVALID') {
      const next = await refreshSession();
      if (next) res = await send();
    } else if (reason === 'TOKEN_REVOKED' || String(reason ?? '').startsWith('ACCOUNT_')) {
      await clearSession();
      onSessionExpired?.();
    }
  }

  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (res.ok) return data as T;
  if (envelope && data && typeof data.status === 'string' && 'results' in data) return data as T;
  if (res.status === 401 && auth) {
    await clearSession();
    onSessionExpired?.();
  }
  throw new ApiError(
    (data?.status as StatusCode) ?? (res.status >= 500 ? 'INTERNAL_ERROR' : 'INVALID_REQUEST'),
    data?.message ?? `Request failed (${res.status}).`,
    res.status,
    data?.details ?? {},
    data?.request_id ?? res.headers.get('x-request-id'),
  );
}

export function newRequestId(): string {
  // RFC4122-ish random id for idempotent submissions (not security-sensitive).
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
