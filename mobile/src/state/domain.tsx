import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import * as api from '@/api/endpoints';
import type { Domain, Preferences } from '@/api/types';

import { useAuth } from './auth';

interface DomainValue {
  domain: Domain;
  setDomain: (d: Domain) => void;
  prefs: Preferences | undefined;
  /** Context of the active domain: primary + current selection, resolved by the server. */
  contextQuery: ReturnType<typeof useContextQuery>;
}

function useContextQuery(domain: Domain, enabled: boolean) {
  return useQuery({ queryKey: ['context', domain], queryFn: () => api.getContext(domain), enabled });
}

const Ctx = createContext<DomainValue | null>(null);

/**
 * The active view (Institutional / Personal). Switching only changes which domain the next requests
 * target; the server re-resolves the timetable for that domain independently (no carry-over).
 */
export function DomainProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const qc = useQueryClient();
  const prefsQ = useQuery({ queryKey: ['prefs'], queryFn: api.getPreferences, enabled: status === 'signedIn' });
  const [domain, setLocal] = useState<Domain>('INSTITUTIONAL');
  const [initialised, setInitialised] = useState(false);

  useEffect(() => {
    if (prefsQ.data && !initialised) {
      setLocal(prefsQ.data.last_active_domain ?? 'INSTITUTIONAL');
      setInitialised(true);
    }
  }, [prefsQ.data, initialised]);

  useEffect(() => {
    if (status === 'signedOut') setInitialised(false);
  }, [status]);

  const setDomain = useCallback(
    (d: Domain) => {
      setLocal(d);
      api.patchPreferences({ last_active_domain: d }).then((p) => qc.setQueryData(['prefs'], p)).catch(() => undefined);
    },
    [qc],
  );

  const contextQuery = useContextQuery(domain, status === 'signedIn');
  const value = useMemo(() => ({ domain, setDomain, prefs: prefsQ.data, contextQuery }), [domain, setDomain, prefsQ.data, contextQuery]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDomain(): DomainValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useDomain outside DomainProvider');
  return v;
}

/** Call after anything that changes archive selection/primary/processing so every screen refreshes. */
export function invalidateTimetableData(qc: ReturnType<typeof useQueryClient>) {
  return Promise.all(
    ['context', 'dashboard', 'entries', 'timetables', 'timetable', 'prefs', 'review'].map((k) => qc.invalidateQueries({ queryKey: [k] })),
  );
}
