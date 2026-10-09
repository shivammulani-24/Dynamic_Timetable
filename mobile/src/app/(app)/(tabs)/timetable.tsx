import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import * as api from '@/api/endpoints';
import type { Entry } from '@/api/types';
import { DomainBar, NoTimetablePrompt, OfflineBanner, Timeline, WarningsList } from '@/components/timetable';
import { Banner, EmptyState, ErrorState, IconButton, LoadingState, Row, Screen, Segmented, Spacer, Text } from '@/components/ui';
import { addDaysIso, DAY_SHORT, fmtDate, isoDow, todayIn } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { useDomain } from '@/state/domain';
import { useTheme } from '@/theme/theme';

/** Weekly calendar. Week start comes from the institution setting; Monday is shown only as a visible fallback label. */
export default function TimetableTab() {
  const t = useTheme();
  const { me, hasRole } = useAuth();
  const { domain, contextQuery } = useDomain();
  const tz = me?.timezone ?? 'Asia/Kolkata';
  const today = todayIn(tz).iso;
  const weekStart = me?.institution.week_start_day ?? 1;
  const [anchor, setAnchor] = useState(today);
  const [scope, setScope] = useState<'mine' | 'all'>('mine');
  const start = addDaysIso(anchor, -((isoDow(anchor) - weekStart + 7) % 7));
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDaysIso(start, i)), [start]);
  const [selected, setSelected] = useState(today);
  const ctx = contextQuery.data;
  const ttId = ctx?.current?.timetable_id;
  const staffView = domain === 'INSTITUTIONAL' && hasRole('PROFESSOR', 'HOD', 'PRINCIPAL', 'ADMIN');

  // "My classes" uses the same engine intent as typing "show my classes on <date>".
  const mine = useQuery({
    queryKey: ['day', domain, selected, ttId],
    queryFn: () => api.search({ intent: 'SHOW_TIMETABLE_FOR_DATE', parameters: { date: selected }, domain }),
    enabled: !!ttId && (scope === 'mine' || !staffView),
  });
  // "Whole timetable" lists every entry visible to the role on that weekday (server applies scope).
  const all = useQuery({
    queryKey: ['entries', domain, ttId, isoDow(selected)],
    queryFn: () => api.listEntries(domain, ttId!, { day_of_week: isoDow(selected), limit: 200 }),
    enabled: !!ttId && staffView && scope === 'all',
  });

  const q = scope === 'all' && staffView ? all : mine;
  const entries: Entry[] = scope === 'all' && staffView ? (all.data?.items ?? []) : (mine.data?.results ?? []);
  const warnings = scope === 'mine' ? (mine.data?.warnings ?? []) : [];

  return (
    <Screen refreshing={q.isRefetching} onRefresh={() => { q.refetch(); contextQuery.refetch(); }}>
      <Row style={{ justifyContent: 'space-between', marginTop: 8 }}>
        <Text variant="title" accessibilityRole="header">
          Timetable
        </Text>
        <Row gap={0}>
          <IconButton icon="chevron-back" label="Previous week" onPress={() => { const a = addDaysIso(anchor, -7); setAnchor(a); setSelected(addDaysIso(selected, -7)); }} />
          <Pressable onPress={() => { setAnchor(today); setSelected(today); }} accessibilityRole="button" hitSlop={6}>
            <Text variant="caption" color={t.colors.primary}>
              Today
            </Text>
          </Pressable>
          <IconButton icon="chevron-forward" label="Next week" onPress={() => { const a = addDaysIso(anchor, 7); setAnchor(a); setSelected(addDaysIso(selected, 7)); }} />
        </Row>
      </Row>
      <DomainBar />
      <Spacer />
      <OfflineBanner updatedAt={q.dataUpdatedAt || undefined} />
      {me?.institution.week_start_day == null ? (
        <Text variant="caption" faint>
          The college hasn't configured a week start; weeks are displayed from Monday for navigation only.
        </Text>
      ) : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingVertical: 12 }}>
        {days.map((d) => {
          const sel = d === selected;
          const isToday = d === today;
          return (
            <Pressable
              key={d}
              onPress={() => setSelected(d)}
              accessibilityRole="tab"
              accessibilityState={{ selected: sel }}
              accessibilityLabel={fmtDate(d)}
              style={{ width: 52, height: 68, borderRadius: 16, alignItems: 'center', justifyContent: 'center', gap: 2, backgroundColor: sel ? t.colors.primary : t.colors.surface, borderWidth: 1, borderColor: isToday && !sel ? t.colors.primary : t.colors.border }}
            >
              <Text variant="micro" color={sel ? t.colors.primaryText : t.colors.textMuted}>
                {DAY_SHORT[isoDow(d)]}
              </Text>
              <Text variant="heading" color={sel ? t.colors.primaryText : t.colors.text}>
                {Number(d.slice(8))}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {staffView ? (
        <>
          <Segmented value={scope} onChange={setScope} options={[{ value: 'mine', label: 'My classes' }, { value: 'all', label: hasRole('PRINCIPAL', 'ADMIN') ? 'Whole college' : 'Department' }]} />
          <Spacer />
        </>
      ) : null}
      {!ttId ? (
        contextQuery.isLoading ? <LoadingState /> : <NoTimetablePrompt domain={domain} message={ctx?.message} />
      ) : q.isLoading ? (
        <LoadingState />
      ) : q.error && !entries.length ? (
        <ErrorState error={q.error} onRetry={q.refetch} />
      ) : mine.data?.status === 'CLARIFICATION_REQUIRED' && scope === 'mine' ? (
        <Banner tone="warning" icon="construct-outline" title={mine.data.message} />
      ) : (
        <View style={{ gap: 12 }}>
          <Text variant="heading">{fmtDate(selected)}</Text>
          <WarningsList warnings={warnings.filter((w) => w.code !== 'CONTAINS_UNVERIFIED' && w.code !== 'TIMETABLE_NEEDS_REVIEW')} />
          {entries.length ? (
            <Timeline entries={entries} domain={domain} timetableId={ttId} />
          ) : (
            <EmptyState icon="sunny-outline" title="No classes" body="Nothing is scheduled on this day in the selected timetable." />
          )}
        </View>
      )}
    </Screen>
  );
}
