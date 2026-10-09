import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Switch, View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { MasterKind } from '@/api/endpoints';
import { Button, Card, Chip, EmptyState, ErrorState, LoadingState, Pill, Row, Screen, Spacer, Text, TextField } from '@/components/ui';
import { notify } from '@/lib/dialogs';

type Field = { key: string; label: string; type?: 'text' | 'number' | 'bool' | 'status' | 'dept' | 'parentBatch' | 'aliasType'; required?: boolean; hint?: string };

const CONFIG: Record<MasterKind, { title: string; idKey: string; fields: Field[]; summary: (x: any) => [string, string] }> = {
  departments: {
    title: 'Departments', idKey: 'department_id',
    fields: [{ key: 'code', label: 'Code', required: true }, { key: 'name', label: 'Name', required: true }, { key: 'is_active', label: 'Active', type: 'bool' }],
    summary: (x) => [`${x.code} · ${x.name}`, x.is_active ? 'Active' : 'Inactive'],
  },
  'academic-years': {
    title: 'Academic years', idKey: 'academic_year_id',
    fields: [{ key: 'label', label: 'Label (YYYY-YYYY)', required: true }, { key: 'start_date', label: 'Start date (YYYY-MM-DD)', required: true }, { key: 'end_date', label: 'End date (YYYY-MM-DD)', required: true }, { key: 'status', label: 'Status', type: 'status' }],
    summary: (x) => [x.label, `${x.status} · ${x.start_date} → ${x.end_date}`],
  },
  batches: {
    title: 'Batches', idKey: 'batch_id',
    fields: [
      { key: 'department_id', label: 'Department', type: 'dept', required: true },
      { key: 'code', label: 'Code used in timetables (e.g. SE-A or SE-A1)', required: true },
      { key: 'cohort_label', label: 'Cohort (e.g. SE-2025)', required: true },
      { key: 'division_label', label: 'Division / group (e.g. A or A1)', required: true },
      { key: 'program_year', label: 'Year of study', type: 'number', required: true },
      { key: 'parent_batch_id', label: 'Parent division (for lab sub-groups)', type: 'parentBatch' },
      { key: 'is_active', label: 'Active', type: 'bool' },
    ],
    summary: (x) => [`${x.code} (${x.department})`, `Year ${x.program_year}${x.parent_batch_id ? ' · sub-group' : ''}`],
  },
  courses: {
    title: 'Courses', idKey: 'course_id',
    fields: [{ key: 'course_code', label: 'Course code / abbreviation' }, { key: 'name', label: 'Name', required: true }, { key: 'department_id', label: 'Department', type: 'dept' }, { key: 'is_active', label: 'Active', type: 'bool' }],
    summary: (x) => [x.name, x.course_code ?? '—'],
  },
  rooms: {
    title: 'Rooms', idKey: 'room_id',
    fields: [
      { key: 'room_code', label: 'Room code (as written in timetables)', required: true },
      { key: 'building', label: 'Building' },
      { key: 'floor_label', label: 'Floor (e.g. 0 for ground, 5)', hint: 'Needed for floor activity and free-room-by-floor.' },
      { key: 'room_type', label: 'Type (CLASSROOM, LAB…)' },
      { key: 'capacity', label: 'Capacity', type: 'number' },
      { key: 'is_active', label: 'Active', type: 'bool' },
    ],
    summary: (x) => [x.room_code, [x.building, x.floor_label != null ? `Floor ${x.floor_label}` : 'No floor', x.capacity ? `${x.capacity} seats` : null].filter(Boolean).join(' · ')],
  },
  aliases: {
    title: 'Aliases', idKey: 'alias_id',
    fields: [
      { key: 'entity_type', label: 'Applies to', type: 'aliasType', required: true },
      { key: 'alias', label: 'Alias as written (e.g. KKD, DBMS, R-508)', required: true },
      { key: 'entity_id', label: 'Target record id', required: true, hint: 'Course/room/batch id, or staff id (see Users).' },
    ],
    summary: (x) => [`${x.alias} → ${x.entity_type} ${x.entity_id}`, ''],
  },
};

export default function MasterData() {
  const { kind } = useLocalSearchParams<{ kind: MasterKind }>();
  const cfg = CONFIG[kind] ?? CONFIG.departments;
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['admin', kind], queryFn: () => api.adminList<any>(kind) });
  const depts = useQuery({ queryKey: ['admin', 'departments'], queryFn: () => api.adminList<any>('departments') });
  const batches = useQuery({ queryKey: ['admin', 'batches'], queryFn: () => api.adminList<any>('batches'), enabled: kind === 'batches' });
  const [editing, setEditing] = useState<any | null>(null);
  const save = useMutation({
    mutationFn: (v: any) => {
      const body: Record<string, unknown> = {};
      for (const fdef of cfg.fields) {
        const raw = v[fdef.key];
        body[fdef.key] = fdef.type === 'number' ? (raw === '' || raw == null ? null : Number(raw)) : raw === '' ? null : raw;
      }
      return v[cfg.idKey] ? api.adminUpdate(kind, v[cfg.idKey], body) : api.adminCreate(kind, body);
    },
    onSuccess: () => {
      setEditing(null);
      qc.invalidateQueries({ queryKey: ['admin'] });
    },
    onError: (e: ApiError) => notify('Not saved', (e.details?.fields as any[])?.map((x) => `${x.field}: ${x.message}`).join('\n') || e.message),
  });
  const del = useMutation({ mutationFn: (id: number) => api.adminDeleteAlias(id), onSuccess: () => list.refetch() });

  const blank = Object.fromEntries(cfg.fields.map((f) => [f.key, f.type === 'bool' ? true : f.type === 'status' ? 'PLANNED' : f.type === 'aliasType' ? 'STAFF' : '']));

  return (
    <Screen edges={[]} refreshing={list.isRefetching} onRefresh={list.refetch}>
      <Stack.Screen options={{ title: cfg.title }} />
      <Spacer />
      {editing ? (
        <Card>
          <Text variant="heading">{editing[cfg.idKey] ? 'Edit' : 'Add'}</Text>
          <Spacer />
          {cfg.fields.map((f) => (
            <FieldInput key={f.key} f={f} value={editing[f.key]} onChange={(v) => setEditing({ ...editing, [f.key]: v })} depts={depts.data?.items ?? []} batches={(batches.data?.items ?? []).filter((b: any) => !b.parent_batch_id && b.department_id === editing.department_id && b.batch_id !== editing.batch_id)} />
          ))}
          <Row gap={8}>
            <Button title="Save" loading={save.isPending} onPress={() => save.mutate(editing)} style={{ flex: 1 }} />
            <Button title="Cancel" variant="ghost" onPress={() => setEditing(null)} />
          </Row>
        </Card>
      ) : (
        <Button title={`Add ${cfg.title.toLowerCase().replace(/s$/, '')}`} icon="add" onPress={() => setEditing(blank)} />
      )}
      <Spacer />
      {list.isLoading ? (
        <LoadingState />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={list.refetch} />
      ) : !list.data?.items.length ? (
        <EmptyState title={`No ${cfg.title.toLowerCase()} yet`} />
      ) : (
        <View style={{ gap: 8 }}>
          {list.data.items.map((x: any) => {
            const [title, sub] = cfg.summary(x);
            return (
              <Card key={x[cfg.idKey]} onPress={kind === 'aliases' ? undefined : () => setEditing({ ...x, capacity: x.capacity ?? '', program_year: String(x.program_year ?? '') })}>
                <Row style={{ justifyContent: 'space-between' }}>
                  <View style={{ flex: 1 }}>
                    <Text variant="bodyStrong">{title}</Text>
                    {sub ? <Text variant="caption" muted>{sub}</Text> : null}
                  </View>
                  {x.status === 'ACTIVE' ? <Pill tone="success" label="Active" /> : null}
                  {kind === 'aliases' ? <Button small variant="ghost" title="Remove" onPress={() => del.mutate(x.alias_id)} /> : null}
                </Row>
              </Card>
            );
          })}
        </View>
      )}
    </Screen>
  );
}

function FieldInput({ f, value, onChange, depts, batches }: { f: Field; value: any; onChange: (v: any) => void; depts: any[]; batches: any[] }) {
  if (f.type === 'bool') {
    return (
      <Row style={{ justifyContent: 'space-between', minHeight: 48 }}>
        <Text>{f.label}</Text>
        <Switch value={!!value} onValueChange={onChange} accessibilityLabel={f.label} />
      </Row>
    );
  }
  const chips = (opts: { v: any; l: string }[]) => (
    <View style={{ marginBottom: 12 }}>
      <Text variant="caption" muted>{f.label}</Text>
      <Row wrap gap={8} style={{ marginTop: 6 }}>
        {opts.map((o) => <Chip key={String(o.v)} label={o.l} selected={value === o.v} onPress={() => onChange(o.v)} />)}
      </Row>
    </View>
  );
  if (f.type === 'status') return chips(['PLANNED', 'ACTIVE', 'CLOSED'].map((s) => ({ v: s, l: s })));
  if (f.type === 'aliasType') return chips(['STAFF', 'COURSE', 'ROOM', 'BATCH'].map((s) => ({ v: s, l: s })));
  if (f.type === 'dept') return chips([...(f.required ? [] : [{ v: null, l: 'None' }]), ...depts.map((d) => ({ v: d.department_id, l: d.code }))]);
  if (f.type === 'parentBatch') return chips([{ v: null, l: 'None (division)' }, ...batches.map((b) => ({ v: b.batch_id, l: b.code }))]);
  return (
    <TextField
      label={f.label + (f.required ? ' *' : '')}
      hint={f.hint}
      value={value == null ? '' : String(value)}
      onChangeText={onChange}
      keyboardType={f.type === 'number' ? 'number-pad' : 'default'}
      autoCapitalize="none"
    />
  );
}
