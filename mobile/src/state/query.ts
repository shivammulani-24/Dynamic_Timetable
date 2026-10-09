import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { onlineManager, QueryClient, type Query } from '@tanstack/react-query';

import { ApiError } from '@/api/client';

onlineManager.setEventListener((setOnline) =>
  NetInfo.addEventListener((s) => setOnline(!!s.isConnected && s.isInternetReachable !== false)),
);

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 24 * 60 * 60 * 1000,
      retry: (count, err) => err instanceof ApiError && err.isNetwork && count < 2,
      refetchOnReconnect: true,
    },
    mutations: {
      // State-changing requests are never silently retried (avoids duplicate submissions).
      retry: false,
      networkMode: 'online',
    },
  },
});

/**
 * Offline cache: only institutional timetable reads are persisted (the official timetable is shared,
 * non-personal data). Personal timetables, search results, notifications and admin data are never
 * written to device storage. The cache is wiped on logout.
 */
const PERSISTABLE = new Set(['dashboard', 'entries', 'context']);
export function shouldPersist(q: Query): boolean {
  const [kind, domain] = q.queryKey as [string, string?];
  return PERSISTABLE.has(kind) && domain === 'INSTITUTIONAL' && q.state.status === 'success';
}

export const persister = createAsyncStoragePersister({ storage: AsyncStorage, key: 'tt.query-cache.v1', throttleTime: 2000 });

export async function wipeLocalCache(): Promise<void> {
  queryClient.clear();
  await persister.removeClient();
}
