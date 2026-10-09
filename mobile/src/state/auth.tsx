import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { ApiError, setSessionExpiredHandler } from '@/api/client';
import * as api from '@/api/endpoints';
import { clearSession, currentSession, loadSession, saveSession } from '@/api/tokenStore';
import type { Me, Role, TokenPair } from '@/api/types';

import { wipeLocalCache } from './query';

type Status = 'loading' | 'signedOut' | 'signedIn' | 'error';

interface AuthValue {
  status: Status;
  me: Me | undefined;
  expiredNotice: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  acceptTokens: (t: TokenPair) => Promise<void>;
  signOut: () => Promise<void>;
  hasRole: (...r: Role[]) => boolean;
  refetchMe: () => void;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [hasSession, setHasSession] = useState<boolean | null>(null);
  const [expiredNotice, setExpiredNotice] = useState(false);

  useEffect(() => {
    loadSession().then((s) => setHasSession(!!s));
    setSessionExpiredHandler(() => {
      setExpiredNotice(true);
      setHasSession(false);
      wipeLocalCache().catch(() => undefined);
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  // Identity and roles always come from the server (never trusted from local state).
  const meQ = useQuery({
    queryKey: ['me'],
    queryFn: api.getMe,
    enabled: hasSession === true,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (meQ.error instanceof ApiError && meQ.error.code === 'UNAUTHENTICATED') setHasSession(false);
  }, [meQ.error]);

  const acceptTokens = useCallback(
    async (t: TokenPair) => {
      await wipeLocalCache(); // never show a previous user's cached data
      await saveSession({ accessToken: t.access_token, refreshToken: t.refresh_token, accessExpiresAt: t.access_expires_at });
      setExpiredNotice(false);
      setHasSession(true);
      await qc.invalidateQueries({ queryKey: ['me'] });
    },
    [qc],
  );

  const signIn = useCallback(async (email: string, password: string) => acceptTokens(await api.login(email.trim(), password)), [acceptTokens]);

  const signOut = useCallback(async () => {
    const s = currentSession();
    try {
      if (s) await api.logout(s.refreshToken);
    } catch {
      // offline logout still clears local credentials; the refresh token expires server-side
    }
    await clearSession();
    await wipeLocalCache();
    setHasSession(false);
  }, []);

  const me = meQ.data;
  let status: Status;
  if (hasSession === null) status = 'loading';
  else if (!hasSession) status = 'signedOut';
  else if (me) status = 'signedIn';
  else if (meQ.error) status = 'error'; // e.g. offline at launch: the root screen offers a retry
  else status = 'loading';

  const value = useMemo<AuthValue>(
    () => ({
      status,
      me,
      expiredNotice,
      signIn,
      acceptTokens,
      signOut,
      hasRole: (...r) => !!me && r.some((x) => me.roles.includes(x)),
      refetchMe: () => void meQ.refetch(),
    }),
    [status, me, meQ, expiredNotice, signIn, acceptTokens, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}
