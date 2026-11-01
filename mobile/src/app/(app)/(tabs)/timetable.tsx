import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, TextInput, View } from 'react-native';

import * as api from '@/api/endpoints';
import type { Entry } from '@/api/types';
import { DomainBar, NoTimetablePrompt, OfflineBanner, Timeline, WarningsList } from '@/components/timetable';
import { Banner, Chip, EmptyState, ErrorState, IconButton, LoadingState, Row, Screen, Segmented, Spacer, Text } from '@/components/ui';
import { addDaysIso, DAY_SHORT, fmtDate, isoDow, todayIn } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { useDomain } from '@/state/domain';
import { useTheme } from '@/theme/theme';

type View_ = 'mine' | 'batch' | 'teacher' | 'room' | 'all';
const PARAM: Record<'batch' | 'teacher' | 'room', 'batch' | 'professor' | 'room'> = { batch: 'batch', teacher: 'professor', room: 'room' };

/** Weekly calendar. Week start comes from the institution setting; Monday is shown only as a visible fallback label.
 * The college timetable is public: anyone can switch from "Mine" to any batch, teacher or room, or the whole college. */
export default function TimetableTab() {
  const t = useTheme();
  const { me } = useAuth();
  const { domain, contextQuery } = useDomain();
  const tz = me?.timezone ?? 'Asia/Kolkata';
  const today = todayIn(tz).iso;
  const weekStart = me?.institution.week_start_day ?? 1;
  const [anchor, setAnchor] = useState(today);
  const [view, setView] = useState<View_>('mine');
  const [picked, setPicked] = useState<Partial<Record<'batch' | 'teacher' | 'room', api.DirectoryItem>>>({});
  const [filter, setFilter] = useState('');
  const [choosing, setChoosing] = useState(false);
  const start = addDaysIso(anchor, -((isoDow(anchor) - weekStart + 7) % 7));
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDaysIso(start, i)), [start]);
  const [selected, setSelected] = useState(today);
  const ctx = contextQuery.data;
  const ttId = ctx?.current?.timetable_id;
  const college = domain === 'INSTITUTIONAL';
  const scope: View_ = college ? view : 'mine';
  const target = scope === 'batch' || scope === 'teacher' || scope === 'room' ? picked[scope] : undefined;
  const needsPick = (scope === 'batch' || scope === 'teacher' || scope === 'room') && !target;

  const directory = useQuery({
    queryKey: ['directory', domain, ttId],
    queryFn: () => api.timetableDirectory(domain),
    enabled: !!ttId && college && scope !== 'mine' && scope !== 'all',
    staleTime: 5 * 60_000,
  });

  // "Mine" and a chosen batch / teacher / room use the same engine intent as typing
  // "show <X>'s classes on <date>".
  const mine = useQuery({
    queryKey: ['day', domain, selected, ttId, scope, target?.key],
    queryFn: () =>
      api.search({
        intent: 'SHOW_TIMETABLE_FOR_DATE',
        parameters: { date: selected, ...(target && scope !== 'mine' && scope !== 'all' ? { [PARAM[scope]]: target.key } : {}) },
        domain,
      }),
    enabled: !!ttId && scope !== 'all' && !needsPick,
  });
  // "Whole college" lists every class on that weekday.
  const all = useQuery({
    queryKey: ['entries', domain, ttId, isoDow(selected)],
    queryFn: async () => {
      // every class that weekday, page by page (the server returns at most 100 per page)
      const items: Entry[] = [];
      let cursor: string | undefined;
      for (let i = 0; i < 10; i += 1) {
        const page = await api.listEntries(domain, ttId!, { day_of_week: isoDow(selected), limit: 100, cursor });
        items.push(...page.items);
        if (!page.pagination.next_cursor) break;
        cursor = page.pagination.next_cursor;
      }
      return { items };
    },
    enabled: !!ttId && scope === 'all',
  });

  const q = scope === 'all' ? all : mine;
  const entries: Entry[] = scope === 'all' ? (all.data?.items ?? []) : (mine.data?.results ?? []);
  const warnings = scope !== 'all' ? (mine.data?.warnings ?? []) : [];
  const list = scope === 'batch' ? directory.data?.batches : scope === 'teacher' ? directory.data?.teachers : scope === 'room' ? directory.data?.rooms : undefined;
  const shown = (list ?? []).filter((i) => `${i.label} ${i.detail ?? ''}`.toLowerCase().includes(filter.trim().toLowerCase())).slice(0, 40);
  const noun = scope === 'batch' ? 'batch' : scope === 'teacher' ? 'teacher' : 'room';

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
      {college ? (
        <>
          <Segmented
            value={scope}
            onChange={(v) => { setView(v); setFilter(''); setChoosing(false); }}
            options={[
              { value: 'mine', label: 'Mine' },
              { value: 'batch', label: 'Batch' },
              { value: 'teacher', label: 'Teacher' },
              { value: 'room', label: 'Room' },
              { value: 'all', label: 'All' },
            ]}
          />
          <Spacer />
          {scope === 'batch' || scope === 'teacher' || scope === 'room' ? (
            target && !choosing ? (
              <Row gap={8} style={{ alignItems: 'center', marginBottom: 8 }}>
                <Text variant="heading" style={{ flex: 1 }} numberOfLines={1}>
                  {target.label}
                  {target.detail ? <Text variant="caption" muted>{`  ${target.detail}`}</Text> : null}
                </Text>
                <Chip label={`Change ${noun}`} icon="swap-horizontal" onPress={() => { setChoosing(true); setFilter(''); }} />
              </Row>
            ) : (
              <View style={{ gap: 8, marginBottom: 8 }}>
                <TextInput
                  value={filter}
                  onChangeText={setFilter}
                  placeholder={`Search a ${noun}${scope === 'teacher' ? ' (name or code)' : ''}`}
                  placeholderTextColor={t.colors.textFaint}
                  accessibilityLabel={`Search a ${noun}`}
                  autoCorrect={false}
                  style={{ minHeight: 44, borderRadius: t.radius.md, borderWidth: 1, borderColor: t.colors.border, backgroundColor: t.colors.surface, color: t.colors.text, paddingHorizontal: 12 }}
                />
                {directory.isLoading ? (
                  <LoadingState />
                ) : (
                  <Row wrap gap={8}>
                    {shown.map((i) => (
                      <Chip
                        key={i.key}
                        label={i.detail && scope === 'teacher' ? `${i.label} (${i.detail})` : i.label}
                        onPress={() => { setPicked({ ...picked, [scope]: i }); setChoosing(false); setFilter(''); }}
                      />
                    ))}
                    {!shown.length ? <Text variant="caption" muted>{`No ${noun} matches “${filter}”.`}</Text> : null}
                  </Row>
                )}
              </View>
            )
          ) : null}
        </>
      ) : null}
      {!ttId ? (
        contextQuery.isLoading ? <LoadingState /> : <NoTimetablePrompt domain={domain} message={ctx?.message} />
      ) : needsPick ? (
        <Text variant="caption" muted>{`Choose a ${noun} to see their timetable. The college timetable is open to everyone.`}</Text>
      ) : q.isLoading ? (
        <LoadingState />
      ) : q.error && !entries.length ? (
        <ErrorState error={q.error} onRetry={q.refetch} />
      ) : mine.data?.status === 'CLARIFICATION_REQUIRED' && scope !== 'all' ? (
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
