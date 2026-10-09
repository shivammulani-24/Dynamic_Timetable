import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, View } from 'react-native';

import type { Domain, Entry, Timetable, Warning } from '@/api/types';
import { fmtDuration, fmtRange, fmtTime } from '@/lib/format';
import { useDomain } from '@/state/domain';
import { useOnline } from '@/state/network';
import { useTheme } from '@/theme/theme';

import { Banner, Card, Pill, Row, Segmented, StatusPill, Text, type IconName } from './ui';

export function useH24(): boolean {
  return useDomain().prefs?.time_format_24h ?? false;
}

/** One class / break. Uncertain values are always visibly marked — never presented as confirmed. */
export function EntryCard({ e, domain, timetableId, compact }: { e: Entry; domain: Domain; timetableId?: string; compact?: boolean }) {
  const t = useTheme();
  const h24 = useH24();
  const isClass = e.kind === 'CLASS';
  const accent = e.status === 'IN_PROGRESS' ? t.colors.success : domain === 'PERSONAL' ? t.colors.personal : t.colors.primary;
  const open = timetableId && isClass && !e.details_withheld
    ? () => router.push({ pathname: '/class/[entryId]', params: { entryId: e.entry_id, domain, timetableId } })
    : undefined;
  if (!isClass) {
    return (
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8, paddingHorizontal: 4 }}>
        <Ionicons name={e.kind === 'BREAK' ? 'cafe-outline' : 'people-outline'} size={16} color={t.colors.textFaint} />
        <Text variant="caption" faint>
          {fmtRange(e.start_time, e.end_time, h24)} · {e.course ?? (e.kind === 'BREAK' ? 'Break' : 'Activity')}
        </Text>
      </View>
    );
  }
  const unverified = e.verification_status !== 'VERIFIED' || e.time_uncertain;
  return (
    <Card onPress={open} accessibilityLabel={`${e.course ?? 'Class'} ${fmtRange(e.start_time, e.end_time)}`} style={{ padding: 0, overflow: 'hidden' }}>
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: 5, backgroundColor: accent }} />
        <View style={{ flex: 1, padding: compact ? 12 : 14, gap: 6 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Row gap={6}>
              <Ionicons name="time-outline" size={14} color={t.colors.textMuted} />
              <Text variant="caption" muted>
                {fmtRange(e.start_time, e.end_time, h24)}
                {e.duration_minutes ? ` · ${fmtDuration(e.duration_minutes)}` : ''}
              </Text>
              {e.time_uncertain ? <Ionicons name="help-circle" size={14} color={t.colors.warning} accessibilityLabel="time unverified" /> : null}
            </Row>
            {e.status === 'IN_PROGRESS' ? <Pill tone="success" label="Now" icon="radio-button-on" /> : null}
          </Row>
          <Text variant="heading" numberOfLines={2}>
            {e.details_withheld ? 'Busy (other batch)' : e.course ?? 'Untitled class'}
          </Text>
          {!e.details_withheld ? (
            <Row wrap gap={12}>
              {e.professor ? <Meta icon="person-outline" text={e.professor} /> : null}
              {e.room ? <Meta icon="location-outline" text={`${e.room}${e.floor ? ` · Floor ${e.floor}` : ''}`} /> : null}
              {e.batch ? <Meta icon="people-outline" text={e.batch} /> : null}
            </Row>
          ) : null}
          {unverified || e.is_tentative ? (
            <Row wrap gap={6}>
              {unverified ? <StatusPill status={e.verification_status === 'VERIFIED' ? 'UNVERIFIED' : e.verification_status} /> : null}
              {e.time_uncertain ? <Pill tone="warning" icon="time" label="Time unverified" /> : null}
              {e.is_tentative ? <Pill tone="warning" icon="construct" label="Tentative" /> : null}
            </Row>
          ) : null}
        </View>
      </View>
    </Card>
  );
}

function Meta({ icon, text }: { icon: IconName; text: string }) {
  const t = useTheme();
  return (
    <Row gap={4}>
      <Ionicons name={icon} size={14} color={t.colors.textMuted} />
      <Text variant="caption" muted numberOfLines={1}>
        {text}
      </Text>
    </Row>
  );
}

/** Vertical timeline grouped by start time; parallel classes (e.g. lab groups) share a slot. */
export function Timeline({ entries, domain, timetableId }: { entries: Entry[]; domain: Domain; timetableId?: string }) {
  const t = useTheme();
  const h24 = useH24();
  const groups: { key: string; items: Entry[] }[] = [];
  for (const e of entries) {
    const key = e.start_time ?? '—';
    const g = groups[groups.length - 1];
    if (g && g.key === key) g.items.push(e);
    else groups.push({ key, items: [e] });
  }
  return (
    <View style={{ gap: 10 }}>
      {groups.map((g) => (
        <View key={g.key + g.items[0].entry_id} style={{ flexDirection: 'row', gap: 10 }}>
          <View style={{ width: 58, alignItems: 'flex-end', paddingTop: 12 }}>
            <Text variant="micro" faint>
              {fmtTime(g.key === '—' ? null : g.key, h24)}
            </Text>
          </View>
          <View style={{ width: 2, backgroundColor: t.colors.border, borderRadius: 1 }} />
          <View style={{ flex: 1, gap: 8 }}>
            {g.items.map((e) => (
              <EntryCard key={e.entry_id + (e.date ?? '')} e={e} domain={domain} timetableId={timetableId} compact />
            ))}
          </View>
        </View>
      ))}
    </View>
  );
}

/** Domain switch + clear indication of which timetable answers will come from. */
export function DomainBar({ showTimetable = true }: { showTimetable?: boolean }) {
  const t = useTheme();
  const { domain, setDomain, contextQuery } = useDomain();
  const ctx = contextQuery.data;
  const current: Timetable | null | undefined = ctx?.current;
  return (
    <View style={{ gap: 10 }}>
      <Segmented
        value={domain}
        onChange={setDomain}
        options={[
          { value: 'INSTITUTIONAL', label: 'College', icon: 'school-outline' },
          { value: 'PERSONAL', label: 'Personal', icon: 'person-circle-outline' },
        ]}
        tones={{ PERSONAL: t.colors.personal }}
      />
      {showTimetable ? (
        <Pressable
          onPress={() => router.push('/(app)/(tabs)/archives')}
          accessibilityRole="button"
          accessibilityLabel="Selected timetable. Opens archives."
          style={{ flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 4 }}
        >
          <Ionicons name={domain === 'PERSONAL' ? 'person' : 'business'} size={14} color={domain === 'PERSONAL' ? t.colors.personal : t.colors.primary} />
          <Text variant="caption" muted numberOfLines={1} style={{ flex: 1 }}>
            {current
              ? `${current.title}${current.selection_type === 'EXPLICIT_ARCHIVE' ? ' · archive' : ' · primary'}${current.academic_year ? ` · ${current.academic_year}` : ''}`
              : contextQuery.isLoading
                ? 'Resolving timetable…'
                : ctx?.status === 'NO_TIMETABLE_SELECTED'
                  ? 'No timetable selected in this view'
                  : ctx?.message ?? 'Timetable unavailable'}
          </Text>
          {current ? <StatusPill status={current.processing_status} /> : null}
          <Ionicons name="chevron-forward" size={14} color={t.colors.textFaint} />
        </Pressable>
      ) : null}
    </View>
  );
}

export function OfflineBanner({ updatedAt }: { updatedAt?: number }) {
  const online = useOnline();
  if (online) return null;
  const when = updatedAt ? new Date(updatedAt).toLocaleString() : null;
  return (
    <Banner
      tone="warning"
      icon="cloud-offline-outline"
      title="You're offline"
      body={when ? `Showing data saved ${when}. It may not be the current official timetable.` : 'Connect to load timetable data.'}
    />
  );
}

export function WarningsList({ warnings }: { warnings: Warning[] }) {
  const shown = warnings.filter((w) => w.code !== 'TIMETABLE_NEEDS_REVIEW' || warnings.length === 1);
  if (!shown.length) return null;
  return (
    <View style={{ gap: 8 }}>
      {shown.map((w, i) => (
        <Banner key={w.code + i} tone="warning" icon="alert-circle-outline" title={w.message} />
      ))}
    </View>
  );
}

export function NoTimetablePrompt({ domain, message }: { domain: Domain; message?: string | null }) {
  const t = useTheme();
  return (
    <Card style={{ alignItems: 'center', gap: 8, paddingVertical: 24 }}>
      <Ionicons name={domain === 'PERSONAL' ? 'cloud-upload-outline' : 'calendar-outline'} size={34} color={domain === 'PERSONAL' ? t.colors.personal : t.colors.primary} />
      <Text variant="heading" style={{ textAlign: 'center' }}>
        {domain === 'PERSONAL' ? 'No personal timetable selected' : 'No official timetable yet'}
      </Text>
      <Text muted style={{ textAlign: 'center' }}>
        {message ??
          (domain === 'PERSONAL'
            ? 'Upload your own timetable or choose one from your archive. College data is never used as a substitute.'
            : 'The college has not activated an official timetable.')}
      </Text>
      {domain === 'PERSONAL' ? (
        <Row gap={8} style={{ marginTop: 6 }}>
          <Pressable onPress={() => router.push({ pathname: '/upload', params: { domain } })} accessibilityRole="button">
            <Text variant="bodyStrong" color={t.colors.personal}>
              Upload
            </Text>
          </Pressable>
          <Text faint>·</Text>
          <Pressable onPress={() => router.push('/(app)/(tabs)/archives')} accessibilityRole="button">
            <Text variant="bodyStrong" color={t.colors.personal}>
              Choose from archive
            </Text>
          </Pressable>
        </Row>
      ) : null}
    </Card>
  );
}
