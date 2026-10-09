import { useInfiniteQuery } from '@tanstack/react-query';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import { Button, Card, EmptyState, ErrorState, LoadingState, Row, Screen, Spacer, Text } from '@/components/ui';
import { fmtDateTime } from '@/lib/format';
import { useTheme } from '@/theme/theme';

export default function Audit() {
  const t = useTheme();
  const q = useInfiniteQuery({
    queryKey: ['audit'],
    queryFn: ({ pageParam }) => api.adminAudit(pageParam ?? undefined),
    initialPageParam: null as string | null,
    getNextPageParam: (l) => l.pagination.next_cursor,
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Screen edges={[]} refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Spacer />
      {q.isLoading ? <LoadingState /> : q.error ? <ErrorState error={q.error} onRetry={q.refetch} /> : !items.length ? <EmptyState title="No audit events" /> : (
        <View style={{ gap: 8 }}>
          {items.map((a: any) => (
            <Card key={a.audit_event_id}>
              <Row style={{ justifyContent: 'space-between' }}>
                <Text variant="bodyStrong" color={a.event_type.includes('DENIED') || a.event_type.includes('FAILED') ? t.colors.danger : undefined}>{a.event_type}</Text>
                <Text variant="caption" faint>{fmtDateTime(a.occurred_at)}</Text>
              </Row>
              <Text variant="caption" muted>
                {a.actor ?? 'system'}{a.target_type ? ` → ${a.target_type} ${String(a.target_id ?? '').slice(0, 8)}` : ''}
              </Text>
              {Object.keys(a.details ?? {}).length ? <Text variant="caption" faint numberOfLines={3}>{JSON.stringify(a.details)}</Text> : null}
            </Card>
          ))}
          {q.hasNextPage ? <Button variant="ghost" title="Load more" onPress={() => q.fetchNextPage()} loading={q.isFetchingNextPage} /> : null}
        </View>
      )}
    </Screen>
  );
}
