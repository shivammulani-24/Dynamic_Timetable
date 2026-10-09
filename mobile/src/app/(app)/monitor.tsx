import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import * as api from '@/api/endpoints';
import { SearchResult } from '@/components/results';
import { Chip, EmptyState, ErrorState, LoadingState, Row, Screen, SectionHeader, Segmented, Spacer, Text } from '@/components/ui';
import { useAuth } from '@/state/auth';

/** Floor activity and free rooms "now" — powered by the same engine intents (Q23 / Q22). */
export default function Monitor() {
  const { hasRole } = useAuth();
  const [floor, setFloor] = useState(5);
  const [mode, setMode] = useState<'floor' | 'free'>('floor');
  const q = useQuery({
    queryKey: ['monitor', mode, floor],
    queryFn: () =>
      api.search(
        mode === 'floor'
          ? { intent: 'FLOOR_ACTIVITY', parameters: { floor }, domain: 'INSTITUTIONAL', query: 'What is happening now on this floor' }
          : { intent: 'FIND_FREE_ROOMS', parameters: { floor }, domain: 'INSTITUTIONAL', query: 'Which rooms are free now' },
      ),
    enabled: hasRole('HOD', 'PRINCIPAL', 'ADMIN'),
    refetchInterval: 60_000,
  });
  if (!hasRole('HOD', 'PRINCIPAL', 'ADMIN')) return <Screen edges={[]}><EmptyState icon="lock-closed-outline" title="Available to HOD, Principal and Admin" /></Screen>;
  return (
    <Screen edges={[]} refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Spacer />
      <Segmented value={mode} onChange={setMode} options={[{ value: 'floor', label: 'Floor activity', icon: 'layers-outline' }, { value: 'free', label: 'Free rooms', icon: 'business-outline' }]} />
      <SectionHeader title="Floor" />
      <Row wrap gap={8}>
        {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((f) => (
          <Chip key={f} label={f === 0 ? 'Ground' : `Floor ${f}`} selected={floor === f} onPress={() => setFloor(f)} />
        ))}
      </Row>
      <Text variant="caption" faint style={{ marginTop: 8 }}>
        Based on the official timetable and the room inventory — scheduled use, not live occupancy. Refreshes every minute.
      </Text>
      <Spacer />
      {q.isLoading ? <LoadingState /> : q.error ? <ErrorState error={q.error} onRetry={q.refetch} /> : q.data ? <SearchResult res={q.data} onChoose={() => undefined} /> : null}
    </Screen>
  );
}
