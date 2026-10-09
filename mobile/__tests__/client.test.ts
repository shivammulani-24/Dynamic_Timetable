import { ApiError, request, setSessionExpiredHandler } from '@/api/client';
import { clearSession, currentSession, saveSession } from '@/api/tokenStore';

type Reply = { status: number; body: unknown };
function mockFetch(replies: Reply[] | ((url: string, init: RequestInit) => Reply)) {
  const calls: { url: string; init: RequestInit }[] = [];
  (global as any).fetch = jest.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const r = typeof replies === 'function' ? replies(url, init) : replies.shift()!;
    const text = JSON.stringify(r.body);
    return {
      ok: r.status >= 200 && r.status < 300,
      status: r.status,
      text: async () => text,
      json: async () => JSON.parse(text),
      clone() { return this; },
      headers: { get: () => null },
    };
  });
  return calls;
}

beforeEach(async () => {
  await clearSession();
  await saveSession({ accessToken: 'old-access', refreshToken: 'r1', accessExpiresAt: '' });
});

test('sends bearer token and parses JSON', async () => {
  const calls = mockFetch([{ status: 200, body: { ok: 1 } }]);
  await expect(request('/me')).resolves.toEqual({ ok: 1 });
  expect((calls[0].init.headers as any).Authorization).toBe('Bearer old-access');
  expect(calls[0].url).toBe('https://api.test/api/v1/me');
});

test('expired access token triggers ONE refresh shared by concurrent requests, then retries', async () => {
  let refreshes = 0;
  const calls = mockFetch((url, init) => {
    if (url.endsWith('/auth/refresh')) {
      refreshes += 1;
      return { status: 200, body: { access_token: 'new-access', refresh_token: 'r2', access_expires_at: 'x', token_type: 'bearer' } };
    }
    const auth = (init.headers as any).Authorization;
    return auth === 'Bearer new-access'
      ? { status: 200, body: { ok: true } }
      : { status: 401, body: { status: 'UNAUTHENTICATED', message: 'expired', details: { reason: 'TOKEN_EXPIRED' } } };
  });
  const [a, b] = await Promise.all([request('/a'), request('/b')]);
  expect(a).toEqual({ ok: true });
  expect(b).toEqual({ ok: true });
  expect(refreshes).toBe(1);
  expect(currentSession()?.refreshToken).toBe('r2');
  expect(calls.filter((c) => c.url.endsWith('/auth/refresh'))).toHaveLength(1);
});

test('rejected refresh clears the session and notifies', async () => {
  const onExpired = jest.fn();
  setSessionExpiredHandler(onExpired);
  mockFetch((url) =>
    url.endsWith('/auth/refresh')
      ? { status: 401, body: { status: 'UNAUTHENTICATED', details: { reason: 'REFRESH_REUSED' } } }
      : { status: 401, body: { status: 'UNAUTHENTICATED', message: 'expired', details: { reason: 'TOKEN_EXPIRED' } } },
  );
  await expect(request('/me')).rejects.toMatchObject({ code: 'UNAUTHENTICATED' });
  expect(currentSession()).toBeNull();
  expect(onExpired).toHaveBeenCalled();
  setSessionExpiredHandler(null);
});

test('application error codes are preserved (client branches on code, not message)', async () => {
  mockFetch([{ status: 403, body: { status: 'ACCESS_DENIED', message: 'nope', details: {}, request_id: 'rid' } }]);
  const err = (await request('/admin/users').catch((e) => e)) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe('ACCESS_DENIED');
  expect(err.httpStatus).toBe(403);
  expect(err.requestId).toBe('rid');
});

test('search envelopes with 4xx are returned, not thrown', async () => {
  const env = { status: 'CLARIFICATION_REQUIRED', results: [], clarification: { kind: 'AMPM' } };
  mockFetch([{ status: 422, body: env }]);
  await expect(request('/search', { method: 'POST', body: {}, envelope: true })).resolves.toEqual(env);
});

test('network failure becomes NETWORK_ERROR', async () => {
  (global as any).fetch = jest.fn(async () => { throw new TypeError('Network request failed'); });
  const err = (await request('/me').catch((e) => e)) as ApiError;
  expect(err.code).toBe('NETWORK_ERROR');
  expect(err.isNetwork).toBe(true);
});
