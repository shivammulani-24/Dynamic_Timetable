import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import { Banner, Button, Chip, ErrorState, LoadingState, Row, Screen, SectionHeader, Spacer, Text, TextField } from '@/components/ui';
import { DAY_NAMES } from '@/lib/format';
import { notify } from '@/lib/dialogs';

export default function InstitutionConfig() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['admin', 'config'], queryFn: api.adminConfig });
  const [v, setV] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    if (q.data && !v) setV(q.data);
  }, [q.data, v]);
  const save = useMutation({
    mutationFn: () =>
      api.adminPutConfig({
        institution_name: v!.institution_name || null,
        week_start_day: v!.week_start_day ?? null,
        lunch_boundary: v!.lunch_boundary || null,
        working_hours_start: v!.working_hours_start || null,
        working_hours_end: v!.working_hours_end || null,
        next_class_lookahead_days: Number(v!.next_class_lookahead_days ?? 7),
      }),
    onSuccess: () => {
      notify('Saved');
      qc.invalidateQueries({ queryKey: ['me'] });
      q.refetch();
    },
    onError: (e: ApiError) => notify('Not saved', (e.details?.fields as any[])?.map((x) => `${x.field}: ${x.message}`).join('\n') || e.message),
  });
  if (q.isLoading || !v) return <LoadingState />;
  if (q.error) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const set = (k: string) => (x: any) => setV({ ...v, [k]: x });
  return (
    <Screen edges={[]}>
      <Spacer />
      <Banner tone="info" title="Unset values are never assumed" body="If week start, lunch or working hours are blank, related questions ask the user or report that the setting is missing." />
      <Spacer />
      <TextField label="Institution name" value={v.institution_name ?? ''} onChangeText={set('institution_name')} />
      <SectionHeader title="Week starts on" />
      <Row wrap gap={8}>
        <Chip label="Not configured" selected={v.week_start_day == null} onPress={() => set('week_start_day')(null)} />
        {[1, 7, 6].map((d) => <Chip key={d} label={DAY_NAMES[d]} selected={v.week_start_day === d} onPress={() => set('week_start_day')(d)} />)}
      </Row>
      <SectionHeader title="Times (24-hour HH:MM)" />
      <TextField label="Lunch ends at (for “after lunch”)" value={v.lunch_boundary ?? ''} onChangeText={set('lunch_boundary')} placeholder="e.g. 14:00" />
      <TextField label="Working hours start (for professor free time)" value={v.working_hours_start ?? ''} onChangeText={set('working_hours_start')} placeholder="e.g. 09:00" />
      <TextField label="Working hours end" value={v.working_hours_end ?? ''} onChangeText={set('working_hours_end')} placeholder="e.g. 17:00" />
      <TextField label="“Next class” looks ahead (days, 0–14)" value={String(v.next_class_lookahead_days ?? 7)} onChangeText={set('next_class_lookahead_days')} keyboardType="number-pad" />
      <Text variant="caption" faint>Changes are audited.</Text>
      <Spacer />
      <Button title="Save settings" loading={save.isPending} onPress={() => save.mutate()} />
    </Screen>
  );
}
