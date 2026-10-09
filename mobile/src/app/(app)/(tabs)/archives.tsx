import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import type { Timetable } from '@/api/types';
import { DomainBar, OfflineBanner } from '@/components/timetable';
import { Banner, Button, Card, EmptyState, ErrorState, LoadingState, Pill, Row, Screen, Spacer, StatusPill, Text } from '@/components/ui';
import { fmtDateTime } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { invalidateTimetableData, useDomain } from '@/state/domain';

export default function Archives() {
  const qc = useQueryClient();
  const { hasRole, me } = useAuth();
  const { domain, contextQuery } = useDomain();
  const q = useInfiniteQuery({
    queryKey: ['timetables', domain],
    queryFn: ({ pageParam }) => api.listTimetables(domain, pageParam ?? undefined),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.pagination.next_cursor,
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.items.some((x) => x.processing_status === 'QUEUED' || x.processing_status === 'PROCESSING')) ? 4000 : false,
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const current = contextQuery.data?.current;
  const canUpload = domain === 'PERSONAL' || hasRole('ADMIN');

  const browse = async (tt: Timetable | null) => {
    await api.setSelection(domain, tt ? tt.timetable_id : null);
    await invalidateTimetableData(qc);
  };

  return (
    <Screen refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Row style={{ justifyContent: 'space-between', marginTop: 8 }}>
        <Text variant="title" accessibilityRole="header">
          Archives
        </Text>
        {canUpload ? (
          <Button small title="Upload" icon="cloud-upload-outline" onPress={() => router.push({ pathname: '/upload', params: { domain } })} />
        ) : null}
      </Row>
      <Spacer />
      <DomainBar showTimetable={false} />
      <Spacer />
      <OfflineBanner />
      <Text variant="caption" muted>
        {domain === 'PERSONAL'
          ? 'Only you can see your personal uploads. Browsing an archive never changes your primary timetable.'
          : 'Official college timetables. Browsing an archive never changes the official timetable.'}
      </Text>
      {current?.selection_type === 'EXPLICIT_ARCHIVE' ? (
        <>
          <Spacer />
          <Banner tone="info" icon="albums-outline" title={`Browsing “${current.title}”`} body="Searches use this archive until you go back to the primary." action="Use primary timetable" onAction={() => browse(null)} />
        </>
      ) : null}
      <Spacer />
      {q.isLoading ? (
        <LoadingState />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={q.refetch} />
      ) : !items.length ? (
        <EmptyState
          icon={domain === 'PERSONAL' ? 'cloud-upload-outline' : 'albums-outline'}
          title={domain === 'PERSONAL' ? 'No personal timetables yet' : 'No official timetables published'}
          body={domain === 'PERSONAL' ? 'Upload a PDF, Excel, Word or photo of your timetable.' : undefined}
          action={canUpload ? 'Upload' : undefined}
          onAction={() => router.push({ pathname: '/upload', params: { domain } })}
        />
      ) : (
        <View style={{ gap: 10 }}>
          {items.map((tt) => {
            const isSelected = current?.timetable_id === tt.timetable_id;
            return (
              <Card key={tt.timetable_id} onPress={() => router.push({ pathname: '/timetable/[id]', params: { id: tt.timetable_id, domain } })} accessibilityLabel={tt.title}>
                <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Text variant="heading" style={{ flex: 1 }} numberOfLines={2}>
                    {tt.title}
                  </Text>
                  {tt.is_primary ? <Pill tone={domain === 'PERSONAL' ? 'personal' : 'primary'} icon="star" label={domain === 'PERSONAL' ? 'Primary' : 'Official'} /> : null}
                </Row>
                <Text variant="caption" muted style={{ marginTop: 4 }}>
                  {[tt.academic_year, tt.term_label, tt.file_format, fmtDateTime(tt.uploaded_at, me?.timezone)].filter(Boolean).join(' · ')}
                </Text>
                <Row gap={8} style={{ marginTop: 10 }} wrap>
                  <StatusPill status={tt.processing_status} />
                  {isSelected && !tt.is_primary ? <Pill tone="info" icon="eye" label="Selected" /> : null}
                </Row>
                {tt.primary_eligible && !isSelected ? (
                  <View style={{ marginTop: 10, alignItems: 'flex-start' }}>
                    <Button small variant="secondary" title="Browse this archive" onPress={() => browse(tt)} />
                  </View>
                ) : null}
              </Card>
            );
          })}
          {q.hasNextPage ? <Button variant="ghost" title="Load more" loading={q.isFetchingNextPage} onPress={() => q.fetchNextPage()} /> : null}
        </View>
      )}
      <Text variant="caption" faint style={{ marginTop: 16, textAlign: 'center' }}>
        Statuses: Ready · Needs review (usable with warnings) · Failed/Unusable (cannot be searched)
      </Text>
    </Screen>
  );
}
