import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';

import * as api from '@/api/endpoints';
import type { Dashboard, Entry, Role } from '@/api/types';
import { DomainBar, NoTimetablePrompt, OfflineBanner, Timeline, useH24, WarningsList } from '@/components/timetable';
import { Banner, Card, ErrorState, IconButton, LoadingState, Pill, Row, Screen, SectionHeader, Spacer, Stat, Text, type IconName } from '@/components/ui';
import { fmtDuration, fmtRange, plural } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { useDomain } from '@/state/domain';
import { useTheme } from '@/theme/theme';

function ask(q: string) {
  router.push({ pathname: '/(app)/(tabs)/search', params: { q } });
}

export default function Home() {
  const t = useTheme();
  const { me, hasRole } = useAuth();
  const { domain, contextQuery } = useDomain();
  const dash = useQuery({ queryKey: ['dashboard', domain], queryFn: () => api.getDashboard(domain), refetchInterval: 60_000 });
  const unread = useQuery({ queryKey: ['unread'], queryFn: api.unreadCount, refetchInterval: 60_000 });

  const d = dash.data;
  const firstName = me?.display_name.replace(/^(Prof\.|Dr\.)\s*/, '').split(' ')[0] ?? '';
  const roleLabel: Record<Role, string> = { STUDENT: 'Student', PROFESSOR: 'Professor', HOD: 'HOD', PRINCIPAL: 'Principal', ADMIN: 'Admin' };

  return (
    <Screen refreshing={dash.isRefetching} onRefresh={() => { dash.refetch(); contextQuery.refetch(); }}>
      <Row style={{ justifyContent: 'space-between', marginTop: 8 }}>
        <View style={{ flex: 1 }}>
          <Text variant="caption" muted>
            {greeting()}
          </Text>
          <Text variant="title" accessibilityRole="header" numberOfLines={1}>
            {firstName}
          </Text>
          <Row gap={6} style={{ marginTop: 4 }} wrap>
            {me?.roles.map((r) => <Pill key={r} label={roleLabel[r]} tone="primary" />)}
          </Row>
        </View>
        <View>
          <IconButton icon="notifications-outline" label="Notifications" onPress={() => router.push('/notifications')} />
          {unread.data?.unread ? (
            <View style={{ position: 'absolute', top: 6, right: 6, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: t.colors.danger, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 }}>
              <Text variant="micro" color="#fff">
                {unread.data.unread > 9 ? '9+' : unread.data.unread}
              </Text>
            </View>
          ) : null}
        </View>
      </Row>
      <Spacer h={16} />
      <DomainBar />
      <Spacer />
      <OfflineBanner updatedAt={dash.dataUpdatedAt || undefined} />
      <Pressable onPress={() => router.push('/(app)/(tabs)/search')} accessibilityRole="search" style={{ marginTop: 12, flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: t.colors.surface, borderRadius: t.radius.md, borderWidth: 1, borderColor: t.colors.border, paddingHorizontal: 14, minHeight: 48 }}>
        <Ionicons name="sparkles-outline" size={18} color={t.colors.primary} />
        <Text muted>Ask about your timetable…</Text>
      </Pressable>

      {dash.isLoading ? <LoadingState /> : dash.error && !d ? <ErrorState error={dash.error} onRetry={dash.refetch} /> : d ? <Body d={d} /> : null}

      <QuickActions />
      {hasRole('ADMIN') && d?.admin ? <AdminSummary a={d.admin} /> : null}
    </Screen>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

function Body({ d }: { d: Dashboard }) {
  const t = useTheme();
  const h24 = useH24();
  const { domain, contextQuery } = useDomain();
  const ttId = contextQuery.data?.current?.timetable_id;
  const status = d.context_status;
  if (status === 'NO_TIMETABLE_SELECTED' || status === 'TIMETABLE_UNUSABLE' || status === 'TIMETABLE_NOT_READY') {
    return (
      <>
        <Spacer h={16} />
        <NoTimetablePrompt domain={domain} message={d.cards.today?.message} />
      </>
    );
  }
  const today = d.cards.today;
  if (today?.clarification?.kind === 'SETUP_REQUIRED') {
    return (
      <>
        <Spacer h={16} />
        <Banner tone="warning" icon="construct-outline" title="Setup required" body={today.clarification.question} />
      </>
    );
  }
  const current: Entry[] = d.cards.current?.results ?? [];
  const next: Entry[] = d.cards.next?.results ?? [];
  const remaining: Entry[] = (d.cards.remaining?.results ?? []).filter((e: Entry) => e.status !== 'IN_PROGRESS');
  const freeToday = d.cards.free_today;

  return (
    <>
      <Spacer h={16} />
      <Card style={{ backgroundColor: domain === 'PERSONAL' ? t.colors.personal : t.colors.primary, borderColor: 'transparent' }}>
        <Text variant="micro" color="rgba(255,255,255,0.8)">
          {current.length ? 'HAPPENING NOW' : 'RIGHT NOW'}
        </Text>
        {current.length ? (
          current.map((e) => (
            <View key={e.entry_id} style={{ marginTop: 6 }}>
              <Text variant="title" color="#fff">
                {e.course}
              </Text>
              <Text variant="caption" color="rgba(255,255,255,0.85)">
                {fmtRange(e.start_time, e.end_time, h24)} · {e.room ?? 'Room not listed'}
                {e.professor ? ` · ${e.professor}` : ''}
              </Text>
            </View>
          ))
        ) : (
          <Text variant="title" color="#fff" style={{ marginTop: 6 }}>
            No class scheduled
          </Text>
        )}
        <View style={{ height: 1, backgroundColor: 'rgba(255,255,255,0.25)', marginVertical: 14 }} />
        <Text variant="micro" color="rgba(255,255,255,0.8)">
          NEXT
        </Text>
        {next.length ? (
          <View style={{ marginTop: 6 }}>
            <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <Text variant="heading" color="#fff" style={{ flex: 1 }}>
                {next[0].course}
                {next.length > 1 ? ` +${next.length - 1}` : ''}
              </Text>
              <Countdown minutes={d.cards.next.meta.minutes_until} />
            </Row>
            <Text variant="caption" color="rgba(255,255,255,0.85)">
              {next[0].date && next[0].day_name ? `${next[0].day_name} · ` : ''}
              {fmtRange(next[0].start_time, next[0].end_time, h24)} · {next[0].room ?? 'Room not listed'}
            </Text>
          </View>
        ) : (
          <Text variant="body" color="#fff" style={{ marginTop: 6 }}>
            {d.cards.next?.message ?? 'No upcoming class.'}
          </Text>
        )}
      </Card>
      <Spacer h={10} />
      <WarningsList warnings={[...(d.cards.next?.warnings ?? []), ...(d.cards.current?.warnings ?? [])].filter((w, i, a) => a.findIndex((x) => x.code === w.code) === i && w.code !== 'CONTAINS_UNVERIFIED')} />

      {freeToday && freeToday.status !== 'UNSUPPORTED_INTENT' ? (
        <>
          <SectionHeader title="Your free periods today" />
          <Row wrap gap={8}>
            {freeToday.results.length ? (
              freeToday.results.map((f: any) => <Pill key={f.start_time} tone="success" label={`${fmtRange(f.start_time, f.end_time, h24)} · ${fmtDuration(f.duration_minutes)}`} />)
            ) : (
              <Text muted>No free time within working hours.</Text>
            )}
          </Row>
        </>
      ) : null}

      <SectionHeader title={`Later today${remaining.length ? ` · ${remaining.length}` : ''}`} action="Full week" onAction={() => router.push('/(app)/(tabs)/timetable')} />
      {remaining.length ? <Timeline entries={remaining} domain={domain} timetableId={ttId} /> : <Text muted>{plural(0, 'more class', 'more classes')} today.</Text>}

      {d.conflicts && d.conflicts.total > 0 ? (
        <>
          <Spacer h={16} />
          <Banner tone="warning" icon="git-compare-outline" title={`${plural(d.conflicts.total, 'possible schedule conflict')}`} body="Professor, room or batch overlaps in the official timetable." action="Review conflicts" onAction={() => router.push('/conflicts')} />
        </>
      ) : null}
    </>
  );
}

function Countdown({ minutes }: { minutes?: number }) {
  const [start] = useState(Date.now());
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((x) => x + 1), 30_000);
    return () => clearInterval(id);
  }, []);
  if (minutes == null) return null;
  const left = Math.max(0, minutes - Math.floor((Date.now() - start) / 60_000));
  return (
    <View style={{ backgroundColor: 'rgba(255,255,255,0.18)', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 }}>
      <Text variant="micro" color="#fff" accessibilityLabel={`starts in ${fmtDuration(left)}`}>
        in {fmtDuration(left)}
      </Text>
    </View>
  );
}

function QuickActions() {
  const { hasRole } = useAuth();
  const { domain } = useDomain();
  const t = useTheme();
  const actions: { icon: IconName; label: string; onPress: () => void; show: boolean }[] = [
    { icon: 'calendar-outline', label: 'This week', onPress: () => router.push('/(app)/(tabs)/timetable'), show: true },
    { icon: 'person-outline', label: 'Find a professor', onPress: () => ask('Which professors teach my batch?'), show: hasRole('STUDENT') },
    { icon: 'cafe-outline', label: 'My free periods', onPress: () => ask('When am I free today?'), show: hasRole('PROFESSOR') && domain === 'INSTITUTIONAL' },
    { icon: 'business-outline', label: 'Free rooms now', onPress: () => ask('Which rooms are free now?'), show: domain === 'INSTITUTIONAL' },
    { icon: 'layers-outline', label: 'Floor activity', onPress: () => router.push('/monitor'), show: hasRole('HOD', 'PRINCIPAL', 'ADMIN') && domain === 'INSTITUTIONAL' },
    { icon: 'git-compare-outline', label: 'Conflicts', onPress: () => router.push('/conflicts'), show: hasRole('HOD', 'PRINCIPAL', 'ADMIN') },
    { icon: 'cloud-upload-outline', label: 'Upload personal', onPress: () => router.push({ pathname: '/upload', params: { domain: 'PERSONAL' } }), show: true },
    { icon: 'document-attach-outline', label: 'Upload official', onPress: () => router.push({ pathname: '/upload', params: { domain: 'INSTITUTIONAL' } }), show: hasRole('ADMIN') },
  ];
  return (
    <>
      <SectionHeader title="Quick actions" />
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
        {actions.filter((a) => a.show).map((a) => (
          <Pressable
            key={a.label}
            onPress={a.onPress}
            accessibilityRole="button"
            style={({ pressed }) => ({ width: '31%', minWidth: 100, flexGrow: 1, minHeight: 84, padding: 12, borderRadius: t.radius.md, backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.border, gap: 8, opacity: pressed ? 0.8 : 1 })}
          >
            <Ionicons name={a.icon} size={22} color={t.colors.primary} />
            <Text variant="caption">{a.label}</Text>
          </Pressable>
        ))}
      </View>
    </>
  );
}

function AdminSummary({ a }: { a: NonNullable<Dashboard['admin']> }) {
  const t = useTheme();
  return (
    <>
      <SectionHeader title="System" action="Admin tools" onAction={() => router.push('/(app)/(tabs)/admin')} />
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
        <Stat label="Active users" value={a.users_active} />
        <Stat label="Pending invitations" value={a.users_invited} />
        <Stat label="Jobs in progress" value={a.jobs_pending} tone={a.jobs_pending ? t.colors.info : undefined} />
        <Stat label="Failed jobs" value={a.jobs_failed} tone={a.jobs_failed ? t.colors.danger : undefined} />
        <Stat label="Uploads needing review" value={a.institutional_needs_review} tone={a.institutional_needs_review ? t.colors.warning : undefined} />
        <Stat label="Active academic year" value={a.active_academic_year ?? '—'} />
      </View>
      {!a.official_default_id ? (
        <>
          <Spacer />
          <Banner tone="warning" title="No official timetable is active" body="Upload, review and activate one so users can see the college timetable." />
        </>
      ) : null}
    </>
  );
}
