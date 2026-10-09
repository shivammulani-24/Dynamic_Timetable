import { useInfiniteQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import { Button, Card, Chip, EmptyState, ErrorState, LoadingState, Row, Screen, Spacer, StatusPill, Text, TextField } from '@/components/ui';

const ROLES = ['STUDENT', 'PROFESSOR', 'HOD', 'PRINCIPAL', 'ADMIN'];

export default function Users() {
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  const [role, setRole] = useState<string | undefined>();
  useEffect(() => {
    const id = setTimeout(() => setQ(text.trim()), 350);
    return () => clearTimeout(id);
  }, [text]);
  const list = useInfiniteQuery({
    queryKey: ['admin-users', q, role],
    queryFn: ({ pageParam }) => api.adminUsers({ q: q || undefined, role, cursor: pageParam ?? undefined }),
    initialPageParam: null as string | null,
    getNextPageParam: (l) => l.pagination.next_cursor,
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Screen edges={[]} refreshing={list.isRefetching} onRefresh={list.refetch}>
      <Spacer />
      <Button title="Register student or staff" icon="person-add-outline" onPress={() => router.push('/admin/new-user')} />
      <Spacer />
      <TextField label="Search name, email or UID" value={text} onChangeText={setText} autoCapitalize="none" />
      <Row wrap gap={8}>
        <Chip label="All roles" selected={!role} onPress={() => setRole(undefined)} />
        {ROLES.map((r) => (
          <Chip key={r} label={r} selected={role === r} onPress={() => setRole(r)} />
        ))}
      </Row>
      <Spacer />
      {list.isLoading ? (
        <LoadingState />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={list.refetch} />
      ) : !items.length ? (
        <EmptyState icon="people-outline" title="No users found" />
      ) : (
        <View style={{ gap: 8 }}>
          <Text variant="caption" muted>
            {list.data?.pages[0].pagination.total} user(s)
          </Text>
          {items.map((u) => (
            <Card key={u.user_id} onPress={() => router.push({ pathname: '/admin/user/[id]', params: { id: u.user_id } })}>
              <Row style={{ justifyContent: 'space-between' }}>
                <Text variant="bodyStrong" style={{ flex: 1 }} numberOfLines={1}>
                  {u.display_name}
                </Text>
                <StatusPill status={u.account_status} />
              </Row>
              <Text variant="caption" muted numberOfLines={1}>
                {u.email}
                {u.uid ? ` · ${u.uid}` : ''}
                {u.short_code ? ` · ${u.short_code}` : ''}
              </Text>
              <Text variant="micro" faint>
                {u.roles.join(' · ')}
              </Text>
            </Card>
          ))}
          {list.hasNextPage ? <Button variant="ghost" title="Load more" onPress={() => list.fetchNextPage()} loading={list.isFetchingNextPage} /> : null}
        </View>
      )}
    </Screen>
  );
}
