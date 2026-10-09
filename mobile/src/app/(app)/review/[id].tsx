import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { Domain, Entry } from '@/api/types';
import { Banner, Button, Card, Chip, EmptyState, ErrorState, LoadingState, Pill, Row, Screen, SectionHeader, Spacer, StatusPill, Text, TextField } from '@/components/ui';
import { DAY_NAMES, fmtRange } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { invalidateTimetableData } from '@/state/domain';
import { useTheme } from '@/theme/theme';
import { confirmAction, notify } from '@/lib/dialogs';

export default function Review() {
  const { id, domain: d } = useLocalSearchParams<{ id: string; domain: Domain }>();
  const domain: Domain = d === 'PERSONAL' ? 'PERSONAL' : 'INSTITUTIONAL';
  const { hasRole } = useAuth();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<'needs' | 'all'>('needs');
  const findings = useQuery({ queryKey: ['findings', domain, id], queryFn: () => api.getFindings(domain, id) });
  const entries = useInfiniteQuery({
    queryKey: ['review-entries', domain, id, filter],
    queryFn: ({ pageParam }) => api.listEntries(domain, id, { review: true, needs_review: filter === 'needs', cursor: pageParam ?? undefined, limit: 30 }),
    initialPageParam: null as string | null,
    getNextPageParam: (l) => l.pagination.next_cursor,
  });
  const remap = useMutation({
    mutationFn: () => api.adminRemap(id),
    onSuccess: async (r) => {
      notify('Mapping refreshed', `${r.changed_entries} entries changed.`);
      await entries.refetch();
      await invalidateTimetableData(qc);
    },
  });
  const items = entries.data?.pages.flatMap((p) => p.items) ?? [];
  const total = entries.data?.pages[0]?.pagination.total ?? 0;
  const blocking = (findings.data?.items ?? []).filter((f) => ['BLOCKING', 'PAGE_ERROR', 'CRITICAL', 'METADATA_WARNING', 'SECTION_FLAG'].includes(f.severity));

  return (
    <Screen edges={[]} refreshing={entries.isRefetching} onRefresh={entries.refetch}>
      <Spacer />
      <Text muted>
        Check uncertain entries against the original document. Verifying confirms the values; corrections keep the original extraction in the audit history.
      </Text>
      {domain === 'INSTITUTIONAL' && hasRole('ADMIN') ? (
        <>
          <Spacer h={8} />
          <Button small variant="ghost" icon="link-outline" title="Re-link to rooms/staff/courses after editing master data" loading={remap.isPending} onPress={() => remap.mutate()} />
        </>
      ) : null}
      {blocking.length ? (
        <>
          <SectionHeader title="Document findings" />
          <View style={{ gap: 8 }}>
            {blocking.slice(0, 12).map((f) => (
              <Banner key={f.finding_id} tone={['BLOCKING', 'PAGE_ERROR', 'CRITICAL'].includes(f.severity) ? 'danger' : 'warning'} title={`${f.source_page ? `p.${f.source_page} · ` : ''}${f.message}`} />
            ))}
          </View>
        </>
      ) : null}
      <SectionHeader title={`Entries (${total})`} />
      <Row gap={8}>
        <Chip label="Needs review" selected={filter === 'needs'} onPress={() => setFilter('needs')} />
        <Chip label="All entries" selected={filter === 'all'} onPress={() => setFilter('all')} />
      </Row>
      <Spacer />
      {entries.isLoading ? (
        <LoadingState />
      ) : entries.error ? (
        <ErrorState error={entries.error} onRetry={entries.refetch} />
      ) : !items.length ? (
        <EmptyState icon="checkmark-done-outline" title="Nothing left to review" />
      ) : (
        <View style={{ gap: 12 }}>
          {items.map((e) => (
            <ReviewCard key={e.entry_id} e={e} domain={domain} ttId={id} onDone={async () => { await entries.refetch(); await invalidateTimetableData(qc); }} />
          ))}
          {entries.hasNextPage ? <Button variant="ghost" title="Load more" onPress={() => entries.fetchNextPage()} loading={entries.isFetchingNextPage} /> : null}
        </View>
      )}
    </Screen>
  );
}

function ReviewCard({ e, domain, ttId, onDone }: { e: Entry; domain: Domain; ttId: string; onDone: () => void }) {
  const t = useTheme();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    day_of_week: e.day_of_week ? String(e.day_of_week) : '',
    start_time: e.start_time ?? '',
    end_time: e.end_time ?? '',
    course: e.raw_labels?.course ?? '',
    professor: e.raw_labels?.professor ?? '',
    batch: e.raw_labels?.batch ?? '',
    room: e.raw_labels?.room ?? '',
  });
  const m = useMutation({
    mutationFn: (changes: Record<string, unknown>) => api.correctEntry(domain, ttId, e.entry_id, changes),
    onSuccess: () => {
      setEditing(false);
      onDone();
    },
    onError: (err: ApiError) => notify('Not saved', err.message),
  });
  const saveEdit = () => {
    const changes: Record<string, unknown> = {};
    const day = Number(form.day_of_week);
    if (form.day_of_week && day !== e.day_of_week) changes.day_of_week = day;
    if (form.start_time !== (e.start_time ?? '')) changes.start_time = form.start_time || null;
    if (form.end_time !== (e.end_time ?? '')) changes.end_time = form.end_time || null;
    for (const k of ['course', 'professor', 'batch', 'room'] as const) {
      if (form[k] !== (e.raw_labels?.[k] ?? '')) changes[k] = form[k] || null;
    }
    if (!Object.keys(changes).length) return setEditing(false);
    m.mutate({ ...changes, reason: 'Edited in review' });
  };
  const section = typeof e.section === 'object' && e.section ? e.section : null;

  return (
    <Card>
      <Row style={{ justifyContent: 'space-between' }}>
        <Text variant="caption" muted>
          p.{e.source_page ?? '?'} · {e.day_name ?? 'No day'} · {fmtRange(e.start_time, e.end_time, true)}
        </Text>
        <StatusPill status={e.verification_status} />
      </Row>
      <Text variant="heading" style={{ marginTop: 4 }}>
        {e.course ?? '(no course)'}
      </Text>
      <Text variant="caption" muted>
        {[e.professor, e.batch, e.room].map((x) => x ?? '—').join(' · ')}
      </Text>
      {section?.title ? (
        <Text variant="caption" faint>
          Section: {section.title}
          {section.is_tentative ? ' (tentative)' : ''}
        </Text>
      ) : null}
      <View style={{ marginTop: 8, padding: 10, borderRadius: 10, backgroundColor: t.colors.surfaceAlt }}>
        <Text variant="micro" muted>
          RAW EXTRACTED TEXT {e.extraction_method === 'OCR' ? '· OCR' : ''}
        </Text>
        <Text variant="caption" style={{ fontFamily: 'monospace' }}>
          {e.raw_text ?? '—'}
        </Text>
        {e.time_label_raw ? (
          <Text variant="caption" muted>
            Time label: “{e.time_label_raw}”
          </Text>
        ) : null}
      </View>
      {(e.all_messages ?? []).filter((x) => x.severity !== 'INFO').map((x, i) => (
        <Row key={x.code + i} gap={6} style={{ marginTop: 6, alignItems: 'flex-start' }}>
          <Pill tone={x.severity === 'CRITICAL' ? 'danger' : 'warning'} label={x.severity} />
          <Text variant="caption" style={{ flex: 1 }}>
            {x.message}
          </Text>
        </Row>
      ))}
      {editing ? (
        <View style={{ marginTop: 12 }}>
          <Text variant="caption" muted>
            Day
          </Text>
          <Row wrap gap={6} style={{ marginVertical: 6 }}>
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
              <Chip key={n} label={DAY_NAMES[n].slice(0, 3)} selected={form.day_of_week === String(n)} onPress={() => setForm({ ...form, day_of_week: String(n) })} />
            ))}
          </Row>
          <Row gap={8}>
            <View style={{ flex: 1 }}>
              <TextField label="Start (HH:MM, 24h)" value={form.start_time} onChangeText={(v) => setForm({ ...form, start_time: v })} keyboardType="numbers-and-punctuation" />
            </View>
            <View style={{ flex: 1 }}>
              <TextField label="End (HH:MM, 24h)" value={form.end_time} onChangeText={(v) => setForm({ ...form, end_time: v })} keyboardType="numbers-and-punctuation" />
            </View>
          </Row>
          <TextField label="Course label" value={form.course} onChangeText={(v) => setForm({ ...form, course: v })} />
          <TextField label="Professor label" value={form.professor} onChangeText={(v) => setForm({ ...form, professor: v })} autoCapitalize="characters" />
          <Row gap={8}>
            <View style={{ flex: 1 }}>
              <TextField label="Batch" value={form.batch} onChangeText={(v) => setForm({ ...form, batch: v })} autoCapitalize="characters" />
            </View>
            <View style={{ flex: 1 }}>
              <TextField label="Room" value={form.room} onChangeText={(v) => setForm({ ...form, room: v })} />
            </View>
          </Row>
          <Row gap={8}>
            <Button small title="Save correction" loading={m.isPending} onPress={saveEdit} style={{ flex: 1 }} />
            <Button small variant="ghost" title="Cancel" onPress={() => setEditing(false)} />
          </Row>
        </View>
      ) : (
        <Row gap={8} style={{ marginTop: 12 }} wrap>
          <Button small title="Verify" icon="checkmark" loading={m.isPending} disabled={!e.day_name || !e.start_time} onPress={() => m.mutate({ verification_status: 'VERIFIED', reason: 'Checked against source' })} />
          <Button small variant="secondary" title="Edit" icon="create-outline" onPress={() => setEditing(true)} />
          <Button small variant="ghost" title="Reject" icon="close" onPress={() => confirmAction('Reject this entry?', 'It will be excluded from searches but kept for audit.', 'Reject', () => m.mutate({ verification_status: 'REJECTED', reason: 'Extraction artifact' }), true)} />
        </Row>
      )}
    </Card>
  );
}
