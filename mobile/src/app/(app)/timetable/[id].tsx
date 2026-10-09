import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { Domain } from '@/api/types';
import { Banner, Button, Card, ErrorState, LoadingState, Pill, Row, Screen, SectionHeader, Spacer, Stat, StatusPill, Text } from '@/components/ui';
import { fmtDate, fmtDateTime } from '@/lib/format';
import { useAuth } from '@/state/auth';
import { invalidateTimetableData, useDomain } from '@/state/domain';
import { useTheme } from '@/theme/theme';
import { confirmAction, notify } from '@/lib/dialogs';

export default function TimetableDetail() {
  const t = useTheme();
  const qc = useQueryClient();
  const { hasRole, me } = useAuth();
  const { setDomain } = useDomain();
  const { id, domain: d } = useLocalSearchParams<{ id: string; domain: Domain }>();
  const domain: Domain = d === 'PERSONAL' ? 'PERSONAL' : 'INSTITUTIONAL';
  const canManage = domain === 'PERSONAL' || hasRole('ADMIN');

  const q = useQuery({
    queryKey: ['timetable', domain, id],
    queryFn: () => api.getTimetable(domain, id),
    refetchInterval: (qq) => (['QUEUED', 'PROCESSING'].includes(qq.state.data?.processing_status ?? '') ? 3000 : false),
  });
  const review = useQuery({ queryKey: ['review', domain, id], queryFn: () => api.getReviewSummary(domain, id), enabled: canManage && !!q.data && !['QUEUED', 'PROCESSING'].includes(q.data.processing_status) });

  const after = async () => {
    await invalidateTimetableData(qc);
    await q.refetch();
  };
  const primary = useMutation({ mutationFn: () => api.makePrimary(domain, id), onSuccess: after, onError: (e: ApiError) => notify('Not changed', e.message) });
  const browse = useMutation({
    mutationFn: () => api.setSelection(domain, id),
    onSuccess: async () => {
      setDomain(domain);
      await after();
      router.push('/(app)/(tabs)/timetable');
    },
    onError: (e: ApiError) => notify('Cannot select', e.message),
  });
  const reprocess = useMutation({ mutationFn: () => api.reprocess(domain, id), onSuccess: after, onError: (e: ApiError) => notify('Cannot reprocess', e.message) });
  const remove = useMutation({
    mutationFn: () => api.removeTimetable(domain, id),
    onSuccess: async () => {
      await invalidateTimetableData(qc);
      router.back();
    },
    onError: (e: ApiError) => notify('Cannot remove', e.message),
  });

  if (q.isLoading) return <LoadingState />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const tt = q.data;
  const s = tt.validation_summary ?? {};
  const processing = ['QUEUED', 'PROCESSING'].includes(tt.processing_status);
  const confirmPrimary = () =>
    confirmAction(domain === 'INSTITUTIONAL' ? 'Activate as official timetable?' : 'Make this your primary timetable?', domain === 'INSTITUTIONAL'
        ? 'All users will see this timetable as the official one and will be notified. The previous official timetable stays in the archive.'
        : 'This only changes your Personal view. The college timetable is not affected.', domain === 'INSTITUTIONAL' ? 'Activate' : 'Make primary', () => primary.mutate());

  return (
    <Screen edges={[]} refreshing={q.isRefetching} onRefresh={q.refetch}>
      <Spacer />
      <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Text variant="title" style={{ flex: 1 }}>
          {tt.title}
        </Text>
        {tt.is_primary ? <Pill tone={domain === 'PERSONAL' ? 'personal' : 'primary'} icon="star" label={domain === 'PERSONAL' ? 'Primary' : 'Official'} /> : null}
      </Row>
      <Text variant="caption" muted>
        {[domain === 'PERSONAL' ? 'Personal' : 'Institutional', tt.academic_year, tt.department, tt.term_label].filter(Boolean).join(' · ')}
      </Text>
      <Spacer />
      <Row wrap gap={8}>
        <StatusPill status={tt.processing_status} />
        <Pill label={tt.file_format} />
        {tt.page_count ? <Pill label={`${tt.page_count} page(s)`} /> : null}
      </Row>
      <Spacer />
      <Card>
        <Text variant="caption" muted>
          {tt.original_filename} · uploaded {fmtDateTime(tt.uploaded_at, me?.timezone)}
        </Text>
        {tt.effective_from || tt.effective_from_raw ? (
          <Text variant="caption" muted>
            Effective from {tt.effective_from ? fmtDate(tt.effective_from) : '—'} {tt.effective_from_raw ? `(“${tt.effective_from_raw}”)` : ''}
          </Text>
        ) : null}
        {tt.parser_version ? (
          <Text variant="caption" faint>
            Parser {tt.parser_version}
          </Text>
        ) : null}
      </Card>

      {processing ? (
        <>
          <Spacer />
          <Banner tone="info" icon="sync" title="Processing…" body={`Job ${tt.job?.status ?? ''}${tt.job?.attempts ? ` · attempt ${tt.job.attempts}/${tt.job.max_attempts}` : ''}`} />
        </>
      ) : null}
      {tt.processing_status === 'FAILED' || tt.processing_status === 'UNUSABLE' ? (
        <>
          <Spacer />
          <Banner tone="danger" icon="ban" title={tt.processing_status === 'FAILED' ? 'Processing failed' : 'Not usable for search'} body={s.status_reason ?? tt.job?.error_message ?? undefined} />
        </>
      ) : null}
      {s.upload_warnings?.map((w) => (
        <View key={w.code} style={{ marginTop: 10 }}>
          <Banner tone="info" title={w.message} />
        </View>
      ))}

      {!processing && s.class_entries != null ? (
        <>
          <SectionHeader title="Extraction summary" />
          <Text variant="caption" muted>
            {s.status_reason}
          </Text>
          <Spacer h={8} />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
            <Stat label="Class entries" value={s.class_entries ?? 0} />
            <Stat label="Verified" value={s.by_status?.VERIFIED ?? 0} tone={t.colors.success} />
            <Stat label="Unverified" value={s.by_status?.UNVERIFIED ?? 0} tone={t.colors.warning} />
            <Stat label="Incomplete" value={s.by_status?.INCOMPLETE ?? 0} tone={t.colors.danger} />
            {review.data ? <Stat label="Ambiguous time labels" value={review.data.ambiguous_time_labels} tone={review.data.ambiguous_time_labels ? t.colors.warning : undefined} /> : null}
            {review.data?.conflicts ? <Stat label="Possible conflicts" value={review.data.conflicts.total} tone={review.data.conflicts.total ? t.colors.warning : undefined} /> : null}
          </View>
          {review.data ? (
            <Text variant="caption" faint style={{ marginTop: 8 }}>
              Missing fields — day {review.data.missing_required_fields.day}, time {review.data.missing_required_fields.time}, professor{' '}
              {review.data.missing_required_fields.professor}, room {review.data.missing_required_fields.room}. Duplicates {review.data.duplicate_entries}.
            </Text>
          ) : null}
          <Text variant="caption" faint style={{ marginTop: 4 }}>
            {s.confidence_note}
          </Text>
        </>
      ) : null}

      {tt.sections?.length ? (
        <>
          <SectionHeader title={`Sections (${tt.sections.length})`} />
          {tt.sections.map((sec) => (
            <Row key={sec.section_id} gap={8} style={{ minHeight: 36 }}>
              <Text variant="caption" muted style={{ width: 52 }}>
                p.{sec.page}
              </Text>
              <Text style={{ flex: 1 }} numberOfLines={1}>
                {sec.title ?? [sec.program_level, sec.divisions.join(', ')].filter(Boolean).join(' ') ?? '—'}
              </Text>
              {sec.is_tentative ? <Pill tone="warning" label="Tentative" /> : null}
              {sec.extraction_method === 'OCR' ? <Pill tone="info" label="OCR" /> : null}
            </Row>
          ))}
        </>
      ) : null}

      <SectionHeader title="Actions" />
      <View style={{ gap: 10 }}>
        {tt.primary_eligible ? <Button title="View & search this timetable" icon="eye-outline" variant="secondary" loading={browse.isPending} onPress={() => browse.mutate()} /> : null}
        {canManage && tt.primary_eligible && !tt.is_primary ? (
          <Button title={domain === 'INSTITUTIONAL' ? 'Activate as official timetable' : 'Make primary'} icon="star-outline" loading={primary.isPending} onPress={confirmPrimary} />
        ) : null}
        {canManage && !processing && (s.class_entries ?? 0) > 0 ? (
          <Button title="Review & correct entries" icon="create-outline" variant="secondary" onPress={() => router.push({ pathname: '/review/[id]', params: { id, domain } })} />
        ) : null}
        {domain === 'INSTITUTIONAL' && hasRole('HOD', 'PRINCIPAL', 'ADMIN') && tt.primary_eligible ? (
          <Button title="Check conflicts" icon="git-compare-outline" variant="secondary" onPress={() => router.push({ pathname: '/conflicts', params: { id } })} />
        ) : null}
        {canManage && ['FAILED', 'UNUSABLE', 'NEEDS_REVIEW', 'READY'].includes(tt.processing_status) && !tt.is_primary ? (
          <Button title="Reprocess" icon="refresh" variant="ghost" loading={reprocess.isPending} onPress={() => reprocess.mutate()} />
        ) : null}
        {canManage && !tt.is_primary && !processing ? (
          <Button
            title="Remove from archive"
            icon="trash-outline"
            variant="ghost"
            onPress={() => confirmAction('Remove this upload?', 'It will no longer appear in your archive.', 'Remove', () => remove.mutate(), true)}
          />
        ) : null}
      </View>
      {!tt.primary_eligible && !processing ? (
        <Text variant="caption" faint style={{ marginTop: 10 }}>
          Failed or unusable uploads cannot become primary or be searched.
        </Text>
      ) : null}
    </Screen>
  );
}
