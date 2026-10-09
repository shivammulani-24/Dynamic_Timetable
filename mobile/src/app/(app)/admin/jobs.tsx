import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import { Card, EmptyState, ErrorState, LoadingState, Pill, Row, Screen, Spacer, StatusPill, Text } from '@/components/ui';
import { fmtDateTime } from '@/lib/format';

const JOB_TONE = { QUEUED: 'QUEUED', RUNNING: 'PROCESSING', SUCCEEDED: 'READY', FAILED: 'FAILED' } as const;

export default function Jobs() {
  const q = useQuery({ queryKey: ['jobs'], queryFn: api.listJobs, refetchInterval: 5000 });
  return (
    <Screen edges={[]} refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Spacer />
      <Text variant="caption" muted>Institutional jobs and your own uploads. Other users' personal uploads are never listed. Refreshes every 5 s.</Text>
      <Spacer />
      {q.isLoading ? <LoadingState /> : q.error ? <ErrorState error={q.error} onRetry={q.refetch} /> : !q.data?.items.length ? <EmptyState title="No processing jobs" /> : (
        <View style={{ gap: 8 }}>
          {q.data.items.map((j) => (
            <Card key={j.job_id} onPress={j.timetable_id && j.domain ? () => router.push({ pathname: '/timetable/[id]', params: { id: j.timetable_id!, domain: j.domain! } }) : undefined}>
              <Row style={{ justifyContent: 'space-between' }}>
                <Row gap={6}>
                  <StatusPill status={JOB_TONE[j.status]} />
                  <Pill label={j.domain === 'PERSONAL' ? 'Personal' : 'Institutional'} tone={j.domain === 'PERSONAL' ? 'personal' : 'primary'} />
                </Row>
                <Text variant="caption" muted>attempt {j.attempts}/{j.max_attempts}</Text>
              </Row>
              <Text variant="caption" muted style={{ marginTop: 6 }}>Queued {fmtDateTime(j.created_at)}{j.finished_at ? ` · finished ${fmtDateTime(j.finished_at)}` : ''}</Text>
              {j.error_message ? <Text variant="caption" style={{ marginTop: 4 }}>{j.error_code}: {j.error_message}</Text> : null}
            </Card>
          ))}
        </View>
      )}
    </Screen>
  );
}
