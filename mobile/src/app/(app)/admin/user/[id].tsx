import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { Role } from '@/api/types';
import { Banner, Button, Card, Chip, ErrorState, LoadingState, Row, Screen, SectionHeader, Spacer, StatusPill, Text } from '@/components/ui';
import { fmtDate, fmtDateTime } from '@/lib/format';
import { confirmAction, notify } from '@/lib/dialogs';

const STAFF_ROLES: Role[] = ['PROFESSOR', 'HOD', 'PRINCIPAL', 'ADMIN'];

export default function AdminUser() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['admin-user', id], queryFn: () => api.adminUser(id) });
  const [roles, setRoles] = useState<Role[]>([]);
  const [devToken, setDevToken] = useState<string | null>(null);
  useEffect(() => {
    if (q.data) setRoles(q.data.roles);
  }, [q.data]);
  const done = () => {
    q.refetch();
    qc.invalidateQueries({ queryKey: ['admin-users'] });
  };
  const err = (e: ApiError) => notify('Not changed', e.message);
  const saveRoles = useMutation({ mutationFn: () => api.adminSetRoles(id, roles), onSuccess: done, onError: err });
  const setStatus = useMutation({ mutationFn: (s: string) => api.adminSetStatus(id, s), onSuccess: done, onError: err });
  const reinvite = useMutation({ mutationFn: () => api.adminReinvite(id), onSuccess: (r) => { setDevToken(r.dev_invitation_token ?? null); done(); }, onError: err });

  if (q.isLoading) return <LoadingState />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const u = q.data;
  const available: Role[] = u.student_id ? ['STUDENT'] : STAFF_ROLES;
  const changed = [...roles].sort().join() !== [...u.roles].sort().join();

  return (
    <Screen edges={[]}>
      <Spacer />
      <Text variant="title">{u.display_name}</Text>
      <Text muted>{u.email}</Text>
      <Row gap={8} style={{ marginTop: 8 }}>
        <StatusPill status={u.account_status} />
        {u.last_login_at ? <Text variant="caption" faint>Last login {fmtDateTime(u.last_login_at)}</Text> : null}
      </Row>

      <SectionHeader title="Roles" />
      <Text variant="caption" muted>
        Changing roles signs the user out so new permissions apply everywhere.
      </Text>
      <Row wrap gap={8} style={{ marginVertical: 10 }}>
        {available.map((r) => (
          <Chip key={r} label={r} selected={roles.includes(r)} onPress={() => setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r])} />
        ))}
      </Row>
      <Button small title="Save roles" disabled={!changed || !roles.length} loading={saveRoles.isPending} onPress={() => saveRoles.mutate()} />

      <SectionHeader title="Account status" />
      <Row wrap gap={8}>
        {u.account_status === 'INVITED' ? (
          <Button small variant="secondary" title="Re-send invitation" loading={reinvite.isPending} onPress={() => reinvite.mutate()} />
        ) : (
          (['ACTIVE', 'SUSPENDED', 'DISABLED'] as const)
            .filter((s) => s !== u.account_status)
            .map((s) => (
              <Button
                key={s}
                small
                variant={s === 'ACTIVE' ? 'secondary' : 'ghost'}
                title={s === 'ACTIVE' ? 'Reactivate' : s === 'SUSPENDED' ? 'Suspend' : 'Disable'}
                onPress={() => confirmAction(`${s === 'ACTIVE' ? 'Reactivate' : s.toLowerCase()} this account?`, s === 'ACTIVE' ? '' : 'All of their sessions end immediately.', 'Confirm', () => setStatus.mutate(s))}
              />
            ))
        )}
      </Row>
      {devToken ? (
        <>
          <Spacer />
          <Banner tone="info" title="Development server: activation code" body={devToken} />
        </>
      ) : null}

      {u.academic_history?.length ? (
        <>
          <SectionHeader title="Academic history" />
          <View style={{ gap: 8 }}>
            {u.academic_history.map((h: any) => (
              <Card key={h.history_id}>
                <Row style={{ justifyContent: 'space-between' }}>
                  <Text variant="bodyStrong">
                    {h.academic_year} · Year {h.year_of_study}
                    {h.semester ? ` · Sem ${h.semester}` : ''}
                  </Text>
                  <StatusPill status={h.status} />
                </Row>
                <Text variant="caption" muted>
                  {h.department} · {h.batch ?? 'No batch'} · {fmtDate(h.effective_from)} → {h.effective_to ? fmtDate(h.effective_to) : 'current'}
                </Text>
                {h.note ? (
                  <Text variant="caption" faint>
                    {h.note}
                  </Text>
                ) : null}
              </Card>
            ))}
          </View>
        </>
      ) : null}
    </Screen>
  );
}
