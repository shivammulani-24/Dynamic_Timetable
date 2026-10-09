import { useQuery } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import type { Conflict } from '@/api/types';
import { useH24 } from '@/components/timetable';
import { Card, Chip, EmptyState, ErrorState, LoadingState, Pill, Row, Screen, Spacer, StatusPill, Text } from '@/components/ui';
import { DAY_NAMES, fmtRange } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { useDomain } from '@/state/domain';

const LABEL: Record<Conflict['type'], string> = { PROFESSOR_OVERLAP: 'Professor', ROOM_OVERLAP: 'Room', BATCH_OVERLAP: 'Batch' };

export default function Conflicts() {
  const { hasRole } = useAuth();
  const h24 = useH24();
  const params = useLocalSearchParams<{ id?: string }>();
  const ctx = useQuery({ queryKey: ['context', 'INSTITUTIONAL'], queryFn: () => api.getContext('INSTITUTIONAL'), enabled: !params.id });
  const { domain } = useDomain();
  const id = params.id ?? ctx.data?.primary?.timetable_id;
  const [type, setType] = useState<Conflict['type'] | 'ALL'>('ALL');
  const [onlyConfirmed, setOnlyConfirmed] = useState(false);
  const q = useQuery({ queryKey: ['conflicts', id], queryFn: () => api.getConflicts(id!), enabled: !!id && hasRole('HOD', 'PRINCIPAL', 'ADMIN') });

  if (!hasRole('HOD', 'PRINCIPAL', 'ADMIN')) return <Screen edges={[]}><EmptyState icon="lock-closed-outline" title="Available to HOD, Principal and Admin" /></Screen>;
  if (!id) return <Screen edges={[]}>{ctx.isLoading ? <LoadingState /> : <EmptyState title="No official timetable is active" />}</Screen>;
  if (q.isLoading) return <LoadingState label="Comparing schedules…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const list = q.data.conflicts.filter((c) => (type === 'ALL' || c.type === type) && (!onlyConfirmed || c.confidence === 'CONFIRMED'));

  return (
    <Screen edges={[]} refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Spacer />
      <Text muted>
        {q.data.total} overlap(s) among {q.data.entries_considered} timed classes{hasRole('PRINCIPAL', 'ADMIN') ? '' : ' in your department'}. “Possible” means the data is unverified or only label-matched — confirm before acting.
      </Text>
      {domain === 'PERSONAL' ? <Text variant="caption" faint>Conflicts are checked for the official college timetable only.</Text> : null}
      <Spacer />
      <Row wrap gap={8}>
        {(['ALL', 'PROFESSOR_OVERLAP', 'ROOM_OVERLAP', 'BATCH_OVERLAP'] as const).map((k) => (
          <Chip key={k} label={k === 'ALL' ? 'All' : LABEL[k]} selected={type === k} onPress={() => setType(k)} />
        ))}
        <Chip label="Confirmed only" icon="shield-checkmark-outline" selected={onlyConfirmed} onPress={() => setOnlyConfirmed(!onlyConfirmed)} />
      </Row>
      <Spacer />
      {!list.length ? (
        <EmptyState icon="checkmark-circle-outline" title="No conflicts in this view" />
      ) : (
        <View style={{ gap: 10 }}>
          {list.map((c, i) => (
            <Card key={i}>
              <Row style={{ justifyContent: 'space-between' }}>
                <Text variant="heading">
                  {LABEL[c.type]}: {c.resource ?? '—'}
                </Text>
                <Pill tone={c.confidence === 'CONFIRMED' ? 'danger' : 'warning'} label={c.confidence} />
              </Row>
              {c.reason ? (
                <Text variant="caption" muted>
                  {c.reason}
                </Text>
              ) : null}
              {c.entries.map((e) => (
                <Row key={e.entry_id} gap={8} style={{ marginTop: 8 }}>
                  <Text variant="caption" style={{ width: 90 }}>
                    {DAY_NAMES[e.day_of_week ?? 0]?.slice(0, 3)} {fmtRange(e.start_time, e.end_time, h24)}
                  </Text>
                  <Text variant="caption" muted style={{ flex: 1 }} numberOfLines={2}>
                    {[e.course, e.professor, e.batch, e.room].filter(Boolean).join(' · ')} (p.{e.source_page})
                  </Text>
                  <StatusPill status={e.verification_status} />
                </Row>
              ))}
            </Card>
          ))}
        </View>
      )}
    </Screen>
  );
}
