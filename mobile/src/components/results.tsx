import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { View } from 'react-native';

import type { Clarification, Entry, SearchResponse } from '@/api/types';
import { fmtDate, fmtDuration, fmtRange, fmtTime, plural } from '@/lib/format';
import { useTheme } from '@/theme/theme';

import { EntryCard, Timeline, useH24, WarningsList } from './timetable';
import { Banner, Button, Card, Chip, EmptyState, Pill, Row, StatusPill, Text } from './ui';

/** Renders a search envelope by its stable `status` and `result_type` codes. */
export function SearchResult({ res, onChoose }: { res: SearchResponse; onChoose: (value: Record<string, unknown>) => void }) {
  const t = useTheme();
  const h24 = useH24();
  const domain = res.context?.domain ?? 'INSTITUTIONAL';
  const ttId = res.context?.timetable_id;

  if (res.status === 'CLARIFICATION_REQUIRED' && res.clarification) {
    return <ClarificationCard c={res.clarification} onChoose={onChoose} />;
  }
  const failure: Partial<Record<SearchResponse['status'], [string, keyof typeof Ionicons.glyphMap]>> = {
    UNSUPPORTED_INTENT: ['Not supported', 'help-buoy-outline'],
    ACCESS_DENIED: ['Not available for your role', 'lock-closed-outline'],
    NO_TIMETABLE_SELECTED: ['No timetable selected', 'calendar-clear-outline'],
    TIMETABLE_UNUSABLE: ['Timetable cannot answer questions', 'ban-outline'],
    TIMETABLE_NOT_READY: ['Still processing', 'hourglass-outline'],
    TIMETABLE_NOT_FOUND: ['Timetable not found', 'search-outline'],
    INVALID_REQUEST: ['Check your question', 'create-outline'],
    RATE_LIMITED: ['Slow down a little', 'speedometer-outline'],
    INTERNAL_ERROR: ['Something went wrong', 'warning-outline'],
  };
  const f = failure[res.status];
  if (f) {
    const examples: string[] = res.details?.examples ?? [];
    return (
      <View style={{ gap: 10 }}>
        <EmptyState
          icon={f[1]}
          title={f[0]}
          body={res.message}
          action={res.status === 'NO_TIMETABLE_SELECTED' ? (domain === 'PERSONAL' ? 'Upload or choose a timetable' : undefined) : undefined}
          onAction={() => router.push('/(app)/(tabs)/archives')}
        />
        {examples.length ? (
          <Row wrap gap={8} style={{ justifyContent: 'center' }}>
            {examples.slice(0, 4).map((q) => (
              <Chip key={q} label={q} onPress={() => onChoose({ __query: q })} />
            ))}
          </Row>
        ) : null}
      </View>
    );
  }

  const header = (
    <View style={{ gap: 10 }}>
      <Card style={{ backgroundColor: t.colors.primarySoft, borderColor: 'transparent' }}>
        <Row gap={10} style={{ alignItems: 'flex-start' }}>
          <Ionicons name={res.status === 'NO_MATCH' ? 'search-outline' : 'sparkles-outline'} size={20} color={t.colors.primary} />
          <Text variant="bodyStrong" style={{ flex: 1 }} accessibilityLiveRegion="polite">
            {res.message}
          </Text>
        </Row>
        {res.status === 'DATA_UNVERIFIED' ? (
          <View style={{ marginTop: 8 }}>
            <Pill tone="warning" icon="alert-circle" label="Includes unverified data" />
          </View>
        ) : null}
      </Card>
      <WarningsList warnings={res.warnings.filter((w) => w.code !== 'CONTAINS_UNVERIFIED')} />
    </View>
  );

  if (res.status === 'NO_MATCH') {
    return (
      <View style={{ gap: 12 }}>
        {header}
        <Text variant="caption" faint style={{ textAlign: 'center' }}>
          Only the selected timetable was searched — results are never pulled from another timetable or view.
        </Text>
      </View>
    );
  }

  const body = (() => {
    switch (res.result_type) {
      case 'ENTRIES':
      case 'SCHEDULED_LOCATION':
        return <EntriesByDate entries={res.results as Entry[]} domain={domain} ttId={ttId} />;
      case 'ENTRY_DETAILS':
        return (res.results as Entry[]).map((e) => <EntryCard key={e.entry_id} e={e} domain={domain} timetableId={ttId} />);
      case 'COURSES':
        return res.results.map((c: any) => (
          <Card key={c.course}>
            <Text variant="heading">{c.course}</Text>
            <Text variant="caption" muted>
              {c.course_code ? `${c.course_code} · ` : ''}
              {plural(c.evidence_count, 'class', 'classes')} {c.batches?.length ? `· ${c.batches.join(', ')}` : ''}
            </Text>
            {c.unverified ? <Pill tone="warning" label="Some entries unverified" /> : null}
          </Card>
        ));
      case 'PROFESSORS':
        return res.results.map((p: any) => (
          <Card key={p.professor}>
            <Row gap={10}>
              <Ionicons name="person-circle-outline" size={28} color={t.colors.primary} />
              <View style={{ flex: 1 }}>
                <Text variant="heading">{p.professor}</Text>
                <Text variant="caption" muted>
                  {p.courses.join(', ') || '—'} · {plural(p.evidence_count, 'class', 'classes')}
                </Text>
              </View>
              {p.unverified ? <Pill tone="warning" label="Unverified" /> : null}
            </Row>
          </Card>
        ));
      case 'FREE_INTERVALS':
        return res.results.map((f: any) => (
          <Card key={f.start_time}>
            <Row style={{ justifyContent: 'space-between' }}>
              <Text variant="heading">{fmtRange(f.start_time, f.end_time, h24)}</Text>
              <Pill tone="success" label={fmtDuration(f.duration_minutes)} />
            </Row>
          </Card>
        ));
      case 'ROOMS':
        return (
          <Row wrap gap={8}>
            {res.results.map((r: any) => (
              <Card key={r.room} style={{ minWidth: 140, flexGrow: 1 }}>
                <Text variant="heading">{r.room}</Text>
                <Text variant="caption" muted>
                  {[r.floor ? `Floor ${r.floor}` : null, r.capacity ? `${r.capacity} seats` : null, r.first_start ? `from ${fmtTime(r.first_start, h24)}` : null, r.classes ? plural(r.classes, 'class', 'classes') : null]
                    .filter(Boolean)
                    .join(' · ')}
                </Text>
              </Card>
            ))}
          </Row>
        );
      case 'ROOM_STATUS':
      case 'SCHEDULE_STATUS':
        return res.results.map((s: any, i: number) => {
          const status: string = s.scheduled_status ?? s.schedule_status;
          const free = status === 'NO_SCHEDULED_CLASS' || status === 'FREE';
          return (
            <View key={i} style={{ gap: 8 }}>
              <Card>
                <Row gap={10}>
                  <Ionicons name={free ? 'checkmark-circle' : status === 'UNCERTAIN' ? 'help-circle' : 'close-circle'} size={30} color={free ? t.colors.success : status === 'UNCERTAIN' ? t.colors.warning : t.colors.danger} />
                  <View style={{ flex: 1 }}>
                    <Text variant="heading">{free ? 'Nothing scheduled' : status === 'UNCERTAIN' ? 'Cannot confirm' : 'Scheduled'}</Text>
                    <Text variant="caption" muted>
                      {s.room ?? s.subject} · {fmtDate(s.date)} {fmtTime(s.time, h24)}
                    </Text>
                  </View>
                </Row>
              </Card>
              {(s.entries ?? []).map((e: Entry) => (
                <EntryCard key={e.entry_id} e={e} domain={domain} timetableId={ttId} />
              ))}
            </View>
          );
        });
      case 'TIMETABLE':
      case 'TIMETABLES':
        return res.results.map((tt: any) => (
          <Card key={tt.timetable_id} onPress={() => router.push({ pathname: '/timetable/[id]', params: { id: tt.timetable_id, domain: tt.domain } })}>
            <Row style={{ justifyContent: 'space-between' }}>
              <Text variant="heading" style={{ flex: 1 }} numberOfLines={1}>
                {tt.title}
              </Text>
              {tt.is_primary ? <Pill tone="primary" icon="star" label="Primary" /> : null}
            </Row>
            <Row gap={8} style={{ marginTop: 6 }}>
              <StatusPill status={tt.processing_status} />
              <Text variant="caption" muted>
                {tt.academic_year ?? ''} {fmtDate(tt.uploaded_at?.slice(0, 10))}
              </Text>
            </Row>
          </Card>
        ));
      case 'ACTION':
        return <Banner tone="success" icon="checkmark-circle" title={res.message} />;
      default:
        return null;
    }
  })();

  return (
    <View style={{ gap: 12 }}>
      {header}
      <View style={{ gap: 10 }}>{body}</View>
      {res.meta?.disclaimer ? (
        <Text variant="caption" faint style={{ textAlign: 'center' }}>
          {res.meta.disclaimer}
        </Text>
      ) : null}
    </View>
  );
}

function EntriesByDate({ entries, domain, ttId }: { entries: Entry[]; domain: 'INSTITUTIONAL' | 'PERSONAL'; ttId?: string }) {
  const groups: { label: string; items: Entry[] }[] = [];
  for (const e of entries) {
    const label = e.date ? fmtDate(e.date) : e.day_name ?? 'Undated';
    const g = groups[groups.length - 1];
    if (g && g.label === label) g.items.push(e);
    else groups.push({ label, items: [e] });
  }
  return (
    <View style={{ gap: 16 }}>
      {groups.map((g) => (
        <View key={g.label} style={{ gap: 8 }}>
          {groups.length > 1 || entries.some((e) => e.date) ? <Text variant="micro" muted>{g.label.toUpperCase()}</Text> : null}
          <Timeline entries={g.items} domain={domain} timetableId={ttId} />
        </View>
      ))}
    </View>
  );
}

export function ClarificationCard({ c, onChoose }: { c: Clarification; onChoose: (value: Record<string, unknown>) => void }) {
  const t = useTheme();
  const icon: Record<string, keyof typeof Ionicons.glyphMap> = {
    AMPM: 'time-outline',
    DATE: 'calendar-outline',
    DATE_RANGE: 'calendar-outline',
    ENTITY_CHOICE: 'list-outline',
    CONFIRMATION: 'shield-checkmark-outline',
    SETUP_REQUIRED: 'construct-outline',
    CONFIGURATION: 'settings-outline',
    SELECT_ARCHIVE: 'archive-outline',
    MISSING_PARAMETER: 'help-circle-outline',
  };
  return (
    <Card style={{ gap: 12, borderColor: t.colors.primary, borderWidth: 1 }}>
      <Row gap={10} style={{ alignItems: 'flex-start' }}>
        <Ionicons name={icon[c.kind] ?? 'help-circle-outline'} size={22} color={t.colors.primary} />
        <Text variant="heading" style={{ flex: 1 }} accessibilityLiveRegion="polite">
          {c.question}
        </Text>
      </Row>
      {c.choices.length ? (
        <View style={{ gap: 8 }}>
          {c.choices.map((ch) =>
            c.kind === 'CONFIRMATION' ? (
              <Button
                key={ch.label}
                title={ch.label}
                variant={ch.value ? 'primary' : 'ghost'}
                onPress={() => (ch.value ? onChoose(ch.value) : onChoose({ __cancel: true }))}
              />
            ) : (
              <Chip key={ch.label} label={ch.label} onPress={() => ch.value && onChoose(ch.value)} />
            ),
          )}
        </View>
      ) : c.kind === 'SETUP_REQUIRED' ? null : (
        <Text variant="caption" muted>
          Add the missing detail to your question and ask again.
        </Text>
      )}
    </Card>
  );
}
