import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';

import * as api from '@/api/endpoints';
import type { Domain, Entry } from '@/api/types';
import { useH24 } from '@/components/timetable';
import { Banner, Button, Card, Divider, EmptyState, ErrorState, LoadingState, Pill, Row, Screen, Spacer, StatusPill, Text, type IconName } from '@/components/ui';
import { fmtDuration, fmtRange } from '@/lib/format';
import { useTheme } from '@/theme/theme';

export default function ClassDetails() {
  const t = useTheme();
  const h24 = useH24();
  const { entryId, domain: d, timetableId } = useLocalSearchParams<{ entryId: string; domain: Domain; timetableId: string }>();
  const domain: Domain = d === 'PERSONAL' ? 'PERSONAL' : 'INSTITUTIONAL';
  const q = useQuery({
    queryKey: ['class', domain, timetableId, entryId],
    queryFn: () =>
      api.search({
        intent: 'SHOW_CLASS_DETAILS',
        parameters: { entry_id: entryId },
        domain,
        selection: timetableId ? { type: 'EXPLICIT_ARCHIVE', timetable_id: timetableId } : undefined,
      }),
  });
  if (q.isLoading) return <LoadingState />;
  if (q.error) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const e: Entry | undefined = q.data?.results?.[0];
  if (!e) return <Screen edges={[]}><EmptyState title="Class not found" body={q.data?.message} /></Screen>;
  const rows: [IconName, string, string | null][] = [
    ['time-outline', 'When', `${e.day_name ?? '—'} · ${fmtRange(e.start_time, e.end_time, h24)}${e.duration_minutes ? ` (${fmtDuration(e.duration_minutes)})` : ''}`],
    ['book-outline', 'Course', [e.course, e.course_code && e.course_code !== e.course ? `(${e.course_code})` : null].filter(Boolean).join(' ') || null],
    ['person-outline', 'Professor', [e.professor, e.professor_code && e.professor_code !== e.professor ? `(${e.professor_code})` : null].filter(Boolean).join(' ') || null],
    ['people-outline', 'Batch', e.batch],
    ['location-outline', 'Scheduled room', e.room ? `${e.room}${e.floor ? ` · Floor ${e.floor}` : ''}` : null],
    ['document-outline', 'Source', `Page ${e.source_page ?? '?'}${typeof e.section === 'string' && e.section ? ` · ${e.section}` : ''}`],
  ];
  return (
    <Screen edges={[]}>
      <Spacer />
      <Text variant="title">{e.course ?? 'Class'}</Text>
      <Row gap={8} wrap style={{ marginTop: 8 }}>
        <StatusPill status={e.verification_status} />
        {e.time_uncertain ? <Pill tone="warning" icon="time" label="Time unverified" /> : null}
        {e.is_tentative ? <Pill tone="warning" icon="construct" label="Tentative" /> : null}
        {e.is_corrected ? <Pill tone="info" icon="create" label="Corrected by reviewer" /> : null}
        <Pill tone={domain === 'PERSONAL' ? 'personal' : 'primary'} label={domain === 'PERSONAL' ? 'Personal' : 'College'} />
      </Row>
      <Spacer />
      <Card style={{ paddingVertical: 4 }}>
        {rows.map(([icon, label, value], i) => (
          <View key={label}>
            {i ? <Divider /> : null}
            <Row gap={12} style={{ minHeight: 56 }}>
              <Ionicons name={icon} size={20} color={t.colors.primary} />
              <View style={{ flex: 1 }}>
                <Text variant="caption" muted>
                  {label}
                </Text>
                <Text>{value ?? 'Not given in the timetable'}</Text>
              </View>
            </Row>
          </View>
        ))}
      </Card>
      {e.warnings.length ? (
        <View style={{ gap: 8, marginTop: 12 }}>
          {e.warnings.map((w, i) => (
            <Banner key={w.code + i} tone="warning" icon="alert-circle-outline" title={w.message} />
          ))}
        </View>
      ) : null}
      <Text variant="caption" faint style={{ marginTop: 12 }}>
        The room shown is where the class is scheduled — not a confirmation of attendance or location.
      </Text>
      {e.raw_text ? (
        <Card style={{ marginTop: 12 }}>
          <Text variant="micro" muted>
            AS WRITTEN IN THE SOURCE
          </Text>
          <Text variant="caption" style={{ fontFamily: 'monospace' }}>
            {e.raw_text}
          </Text>
        </Card>
      ) : null}
      <Spacer />
      <View style={{ gap: 8 }}>
        {e.course_code ? (
          <Button variant="secondary" icon="search-outline" title={`All ${e.course_code} classes`} onPress={() => router.push({ pathname: '/(app)/(tabs)/search', params: { q: `Find all ${e.course_code} classes` } })} />
        ) : null}
        {e.professor ? (
          <Button variant="secondary" icon="person-outline" title={`${e.professor}'s schedule`} onPress={() => router.push({ pathname: '/(app)/(tabs)/search', params: { q: `Show professor ${e.professor_code ?? e.professor} schedule` } })} />
        ) : null}
      </View>
    </Screen>
  );
}
