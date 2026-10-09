import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Switch, View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { Preferences } from '@/api/types';
import { Banner, Button, Card, Divider, ListRow, Pill, Row, Screen, SectionHeader, Segmented, Spacer, Text, TextField } from '@/components/ui';
import { fmtDate } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { invalidateTimetableData, useDomain } from '@/state/domain';
import { useTheme } from '@/theme/theme';
import { confirmAction, notify } from '@/lib/dialogs';

export default function Profile() {
  const t = useTheme();
  const qc = useQueryClient();
  const { me, signOut, refetchMe } = useAuth();
  const { prefs } = useDomain();
  const [tz, setTz] = useState<string | null>(null);
  const [tzError, setTzError] = useState<string | undefined>();

  const save = useMutation({
    mutationFn: (p: Partial<Preferences>) => api.patchPreferences(p),
    onSuccess: async (p) => {
      qc.setQueryData(['prefs'], p);
      await invalidateTimetableData(qc);
      refetchMe();
    },
    onError: (e: ApiError) => notify('Not saved', e.message),
  });

  if (!me || !prefs) return null;
  const placement = me.student?.placement;

  const toggle = (key: keyof Preferences, label: string) => (
    <Row style={{ justifyContent: 'space-between', minHeight: 48 }}>
      <Text style={{ flex: 1 }}>{label}</Text>
      <Switch
        accessibilityLabel={label}
        value={Boolean(prefs[key])}
        onValueChange={(v) => save.mutate({ [key]: v } as Partial<Preferences>)}
        trackColor={{ true: t.colors.primary, false: t.colors.border }}
      />
    </Row>
  );

  return (
    <Screen>
      <Spacer h={8} />
      <Text variant="title" accessibilityRole="header">
        Profile
      </Text>
      <Spacer />
      <Card>
        <Text variant="heading">{me.display_name}</Text>
        <Text variant="caption" muted>
          {me.email}
        </Text>
        <Row gap={6} wrap style={{ marginTop: 8 }}>
          {me.roles.map((r) => (
            <Pill key={r} tone="primary" label={r} />
          ))}
        </Row>
        {me.student ? (
          <>
            <Spacer />
            <Divider />
            <Spacer />
            <Text variant="caption" muted>
              Student UID {me.student.uid}
            </Text>
            {placement ? (
              <Text>
                {placement.department} · Year {placement.year_of_study}
                {placement.semester ? ` · Sem ${placement.semester}` : ''} · {placement.batch ?? 'No batch'} ({placement.academic_year}) since {fmtDate(placement.effective_from)}
              </Text>
            ) : null}
            {me.student.setup_required ? (
              <>
                <Spacer h={8} />
                <Banner tone="warning" icon="construct-outline" title="Batch not linked yet" body="Ask the Admin office to complete your academic placement to see your college timetable." />
              </>
            ) : null}
          </>
        ) : null}
        {me.staff ? (
          <Text variant="caption" muted style={{ marginTop: 8 }}>
            {me.staff.department ?? 'No department'}
          </Text>
        ) : null}
      </Card>

      <SectionHeader title="Timetable selection" />
      <Card>
        <Text variant="caption" muted>
          When you return to a view, start from…
        </Text>
        <Spacer h={8} />
        <Segmented
          value={prefs.selection_mode}
          onChange={(v) => save.mutate({ selection_mode: v })}
          options={[
            { value: 'REMEMBER_LAST', label: 'Last selected' },
            { value: 'ALWAYS_USE_PRIMARY', label: 'Always primary' },
          ]}
        />
        <Text variant="caption" faint style={{ marginTop: 8 }}>
          Selections are remembered separately for the College and Personal views and are kept across logins.
        </Text>
      </Card>

      <SectionHeader title="Time & display" />
      <Card>
        <TextField
          label="Timezone (IANA, e.g. Asia/Kolkata)"
          value={tz ?? prefs.timezone}
          onChangeText={(v) => {
            setTz(v);
            setTzError(undefined);
          }}
          autoCapitalize="none"
          autoCorrect={false}
          error={tzError}
          hint="Used for “today”, “tomorrow” and “now”."
        />
        {tz !== null && tz !== prefs.timezone ? (
          <Button
            small
            title="Save timezone"
            loading={save.isPending}
            onPress={() =>
              save.mutate(
                { timezone: tz.trim() },
                { onSuccess: () => setTz(null), onError: (e) => setTzError((e as ApiError).message) },
              )
            }
          />
        ) : null}
        <Spacer />
        <Text variant="caption" muted>
          Appearance
        </Text>
        <Spacer h={6} />
        <Segmented
          value={prefs.theme}
          onChange={(v) => save.mutate({ theme: v })}
          options={[
            { value: 'system', label: 'System' },
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
          ]}
        />
        <Spacer h={6} />
        {toggle('time_format_24h', '24-hour clock')}
      </Card>

      <SectionHeader title="Notifications & privacy" />
      <Card>
        {toggle('notify_official_timetable', 'New official timetable activated')}
        {toggle('notify_processing', 'My uploads finished processing')}
        {toggle('search_history_enabled', 'Keep my recent searches')}
      </Card>

      <SectionHeader title="Account" />
      <Card style={{ paddingVertical: 4 }}>
        <ListRow icon="notifications-outline" title="Notifications" onPress={() => router.push('/notifications')} />
        <Divider />
        <ListRow icon="key-outline" title="Change password" onPress={() => router.push('/password')} />
        <Divider />
        <ListRow
          icon="log-out-outline"
          title="Sign out"
          tone={t.colors.danger}
          onPress={() => confirmAction('Sign out?', 'Cached timetable data on this device will be cleared.', 'Sign out', signOut, true)}
        />
      </Card>
      <View style={{ height: 24 }} />
      <Text variant="caption" faint style={{ textAlign: 'center' }}>
        {me.institution.name ?? 'Dynamic Timetable'}
      </Text>
    </Screen>
  );
}
