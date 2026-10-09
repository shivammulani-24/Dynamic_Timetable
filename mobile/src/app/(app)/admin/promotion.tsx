import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import { Banner, Button, Card, Chip, EmptyState, LoadingState, Row, Screen, SectionHeader, Spacer, StatusPill, Text, TextField } from '@/components/ui';
import { useTheme } from '@/theme/theme';
import { confirmAction, notify } from '@/lib/dialogs';

const OUTCOMES = [
  ['PROMOTE', 'Promote'],
  ['REPEAT', 'Repeat year'],
  ['PAUSE', 'Pause'],
  ['RESUME', 'Resume'],
  ['WITHDRAW', 'Withdraw'],
  ['GRADUATE', 'Graduate'],
] as const;

export default function Promotion() {
  const t = useTheme();
  const qc = useQueryClient();
  const years = useQuery({ queryKey: ['admin', 'academic-years'], queryFn: () => api.adminList<any>('academic-years') });
  const batches = useQuery({ queryKey: ['admin', 'batches'], queryFn: () => api.adminList<any>('batches') });
  const [fromBatch, setFromBatch] = useState<number | undefined>();
  const [fromYear, setFromYear] = useState<number | undefined>();
  const eligible = useQuery({ queryKey: ['eligible', fromBatch, fromYear], queryFn: () => api.adminEligible({ batch_id: fromBatch, academic_year_id: fromYear }) });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number][0]>('PROMOTE');
  const [toYear, setToYear] = useState<number | null>(null);
  const [toBatch, setToBatch] = useState<number | null>(null);
  const [yos, setYos] = useState('');
  const [sem, setSem] = useState('');
  const [eff, setEff] = useState(new Date().toISOString().slice(0, 10));
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof api.adminPromotionPreview>> | null>(null);

  const items = () =>
    [...selected].map((student_id) => ({
      student_id,
      outcome,
      effective_date: eff,
      ...(toYear ? { academic_year_id: toYear } : {}),
      ...(yos ? { year_of_study: Number(yos) } : {}),
      ...(sem ? { semester: Number(sem) } : {}),
      ...(toBatch ? { batch_id: toBatch } : {}),
    }));
  const prev = useMutation({ mutationFn: () => api.adminPromotionPreview(items()), onSuccess: setPreview, onError: (e: ApiError) => notify('Check the form', e.message) });
  const confirm = useMutation({
    mutationFn: () => api.adminPromotionConfirm(items()),
    onSuccess: (r) => {
      notify('Confirmed', `${r.confirmed} student record(s) updated. Previous placements were preserved in history.`);
      setPreview(null);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ['eligible'] });
    },
    onError: (e: ApiError) => notify('Nothing was changed', e.message),
  });
  const toggle = (id: string) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
    setPreview(null);
  };
  const list = eligible.data?.items ?? [];

  return (
    <Screen edges={[]}>
      <Spacer />
      <Banner tone="info" title="Nothing changes until you confirm" body="Each confirmation closes the current placement and opens the next one in a single transaction. History is never overwritten." />
      <SectionHeader title="1 · Choose students" />
      <Text variant="caption" muted>Current batch</Text>
      <Row wrap gap={8} style={{ marginVertical: 6 }}>
        <Chip label="Any" selected={!fromBatch} onPress={() => setFromBatch(undefined)} />
        {batches.data?.items.map((b: any) => <Chip key={b.batch_id} label={`${b.code} (${b.department})`} selected={fromBatch === b.batch_id} onPress={() => setFromBatch(b.batch_id)} />)}
      </Row>
      <Text variant="caption" muted>Current academic year</Text>
      <Row wrap gap={8} style={{ marginVertical: 6 }}>
        <Chip label="Any" selected={!fromYear} onPress={() => setFromYear(undefined)} />
        {years.data?.items.map((y: any) => <Chip key={y.academic_year_id} label={y.label} selected={fromYear === y.academic_year_id} onPress={() => setFromYear(y.academic_year_id)} />)}
      </Row>
      {eligible.isLoading ? (
        <LoadingState />
      ) : !list.length ? (
        <EmptyState icon="people-outline" title="No students with an open placement match" />
      ) : (
        <Card style={{ paddingVertical: 4 }}>
          <Row style={{ justifyContent: 'space-between', minHeight: 44 }}>
            <Text variant="caption" muted>{selected.size} of {list.length} selected</Text>
            <Button small variant="ghost" title={selected.size === list.length ? 'Clear' : 'Select all'} onPress={() => setSelected(selected.size === list.length ? new Set() : new Set(list.map((s) => s.student_id)))} />
          </Row>
          {list.map((s) => (
            <Pressable key={s.student_id} onPress={() => toggle(s.student_id)} accessibilityRole="checkbox" accessibilityState={{ checked: selected.has(s.student_id) }} style={{ flexDirection: 'row', gap: 10, alignItems: 'center', minHeight: 52 }}>
              <View style={{ width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: t.colors.primary, backgroundColor: selected.has(s.student_id) ? t.colors.primary : 'transparent' }} />
              <View style={{ flex: 1 }}>
                <Text variant="bodyStrong">{s.name}</Text>
                <Text variant="caption" muted>
                  {s.uid} · {s.current.academic_year} · Y{s.current.year_of_study} · {s.current.batch ?? 'no batch'}
                </Text>
              </View>
              <StatusPill status={s.current.status} />
            </Pressable>
          ))}
        </Card>
      )}

      <SectionHeader title="2 · Outcome" />
      <Row wrap gap={8}>
        {OUTCOMES.map(([k, l]) => <Chip key={k} label={l} selected={outcome === k} onPress={() => { setOutcome(k); setPreview(null); }} />)}
      </Row>
      {['PROMOTE', 'REPEAT', 'RESUME'].includes(outcome) ? (
        <>
          <Spacer />
          <Text variant="caption" muted>New academic year {outcome === 'PROMOTE' ? '(required)' : '(optional)'}</Text>
          <Row wrap gap={8} style={{ marginVertical: 6 }}>
            {years.data?.items.filter((y: any) => y.status !== 'CLOSED').map((y: any) => <Chip key={y.academic_year_id} label={y.label} selected={toYear === y.academic_year_id} onPress={() => setToYear(y.academic_year_id)} />)}
          </Row>
          <Row gap={8}>
            <View style={{ flex: 1 }}><TextField label={`Year of study${outcome === 'PROMOTE' ? ' *' : ''}`} value={yos} onChangeText={setYos} keyboardType="number-pad" /></View>
            <View style={{ flex: 1 }}><TextField label="Semester" value={sem} onChangeText={setSem} keyboardType="number-pad" /></View>
          </Row>
          <Text variant="caption" muted>New batch</Text>
          <Row wrap gap={8} style={{ marginVertical: 6 }}>
            <Chip label="Keep/none" selected={toBatch === null} onPress={() => setToBatch(null)} />
            {batches.data?.items.map((b: any) => <Chip key={b.batch_id} label={b.code} selected={toBatch === b.batch_id} onPress={() => setToBatch(b.batch_id)} />)}
          </Row>
        </>
      ) : null}
      <TextField label="Effective date (YYYY-MM-DD)" value={eff} onChangeText={setEff} />

      <SectionHeader title="3 · Review" />
      <Button title="Preview changes" variant="secondary" disabled={!selected.size} loading={prev.isPending} onPress={() => prev.mutate()} />
      {preview ? (
        <View style={{ gap: 8, marginTop: 12 }}>
          {preview.errors.map((e) => <Banner key={e.student_id} tone="danger" title={e.message} body={list.find((s) => s.student_id === e.student_id)?.name} />)}
          {preview.items.map((it: any) => (
            <Card key={it.student_id}>
              <Text variant="bodyStrong">{it.name} ({it.uid})</Text>
              <Text variant="caption" muted>
                {it.current ? `${it.current.academic_year} Y${it.current.year_of_study} ${it.current.batch ?? ''} → closes as ${it.close_current_as}` : 'No open placement'}
              </Text>
              <Text variant="caption">
                {it.new_placement ? `New: year ${it.new_placement.year_of_study}${it.new_placement.semester ? `, sem ${it.new_placement.semester}` : ''} · ${it.new_placement.status}` : 'No new placement'}
              </Text>
            </Card>
          ))}
          <Button
            title={`Confirm ${preview.items.length} change(s)`}
            icon="shield-checkmark-outline"
            disabled={!preview.can_confirm}
            loading={confirm.isPending}
            onPress={() => confirmAction('Confirm academic changes?', 'This is recorded with your name in the audit log.', 'Confirm', () => confirm.mutate())}
          />
          {!preview.can_confirm ? <Text variant="caption" color={t.colors.danger}>Fix the errors above before confirming — the whole batch is applied together or not at all.</Text> : null}
        </View>
      ) : null}
    </Screen>
  );
}
