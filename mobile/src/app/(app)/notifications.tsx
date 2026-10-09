import { Ionicons } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import type { NotificationItem } from '@/api/types';
import { Button, Card, EmptyState, ErrorState, LoadingState, Row, Screen, Spacer, Text } from '@/components/ui';
import { relativeFromNow } from '@/lib/format';
import { invalidateTimetableData } from '@/state/domain';
import { useTheme } from '@/theme/theme';

const ICON: Record<string, keyof typeof Ionicons.glyphMap> = {
  OFFICIAL_TIMETABLE_ACTIVATED: 'megaphone-outline',
  PROCESSING_COMPLETED: 'checkmark-done-outline',
  PROCESSING_FAILED: 'alert-circle-outline',
};

export default function Notifications() {
  const t = useTheme();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['notifications'], queryFn: api.listNotifications });
  const all = useMutation({ mutationFn: api.markAllRead, onSuccess: () => { q.refetch(); qc.invalidateQueries({ queryKey: ['unread'] }); } });

  const open = async (n: NotificationItem) => {
    if (!n.read_at) {
      await api.markRead(n.notification_id).catch(() => undefined);
      qc.invalidateQueries({ queryKey: ['unread'] });
      q.refetch();
    }
    if (n.kind === 'OFFICIAL_TIMETABLE_ACTIVATED') {
      await invalidateTimetableData(qc); // never keep showing the old official timetable as current
      router.push('/(app)/(tabs)');
    } else if (n.data?.timetable_id && n.data?.domain) {
      router.push({ pathname: '/timetable/[id]', params: { id: n.data.timetable_id, domain: n.data.domain } });
    }
  };

  return (
    <Screen edges={[]} refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Spacer />
      {q.data?.unread ? <Button small variant="ghost" title="Mark all as read" onPress={() => all.mutate()} style={{ alignSelf: 'flex-end' }} /> : null}
      {q.isLoading ? (
        <LoadingState />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={q.refetch} />
      ) : !q.data?.items.length ? (
        <EmptyState icon="notifications-off-outline" title="No notifications" body="You'll hear about new official timetables and your upload results here." />
      ) : (
        <View style={{ gap: 10 }}>
          {q.data.items.map((n) => (
            <Card key={n.notification_id} onPress={() => open(n)} style={!n.read_at ? { borderColor: t.colors.primary } : undefined}>
              <Row gap={12} style={{ alignItems: 'flex-start' }}>
                <Ionicons name={ICON[n.kind] ?? 'notifications-outline'} size={22} color={n.kind === 'PROCESSING_FAILED' ? t.colors.danger : t.colors.primary} />
                <View style={{ flex: 1 }}>
                  <Text variant="bodyStrong">{n.title}</Text>
                  <Text variant="caption" muted>
                    {n.body}
                  </Text>
                  <Text variant="micro" faint style={{ marginTop: 4 }}>
                    {relativeFromNow(new Date(n.created_at).getTime())}
                  </Text>
                </View>
                {!n.read_at ? <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: t.colors.primary, marginTop: 6 }} /> : null}
              </Row>
            </Card>
          ))}
        </View>
      )}
    </Screen>
  );
}
