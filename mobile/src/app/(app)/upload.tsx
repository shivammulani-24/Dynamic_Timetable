import { Ionicons } from '@expo/vector-icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as DocumentPicker from 'expo-document-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { newRequestId, type ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { Domain, Timetable } from '@/api/types';
import { Banner, Button, Card, Chip, EmptyState, Pill, Row, Screen, SectionHeader, Spacer, StatusPill, Text, TextField } from '@/components/ui';
import { useAuth } from '@/state/auth';
import { invalidateTimetableData } from '@/state/domain';
import { useOnline } from '@/state/network';
import { useTheme } from '@/theme/theme';

const MAX_MB = 15;
const EXTENSIONS = ['.pdf', '.xlsx', '.xls', '.csv', '.docx', '.doc', '.jpg', '.jpeg', '.png'];
const MIME = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'text/csv',
  'text/comma-separated-values',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/msword',
  'image/jpeg',
  'image/png',
];

type Picked = { uri: string; name: string; size?: number; mimeType?: string | null; file?: File };

export default function Upload() {
  const t = useTheme();
  const qc = useQueryClient();
  const online = useOnline();
  const { hasRole } = useAuth();
  const params = useLocalSearchParams<{ domain?: string }>();
  const domain: Domain = params.domain === 'INSTITUTIONAL' && hasRole('ADMIN') ? 'INSTITUTIONAL' : 'PERSONAL';
  const [file, setFile] = useState<Picked | null>(null);
  const [title, setTitle] = useState('');
  const [yearId, setYearId] = useState<number | null>(null);
  const [deptId, setDeptId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploaded, setUploaded] = useState<(Timetable & { warnings: { code: string; message: string }[] }) | null>(null);
  const requestId = useRef<string>(newRequestId());

  const years = useQuery({ queryKey: ['admin', 'academic-years'], queryFn: () => api.adminList<any>('academic-years'), enabled: domain === 'INSTITUTIONAL' });
  const depts = useQuery({ queryKey: ['admin', 'departments'], queryFn: () => api.adminList<any>('departments'), enabled: domain === 'INSTITUTIONAL' });
  useEffect(() => {
    const active = years.data?.items.find((y: any) => y.status === 'ACTIVE');
    if (active && yearId === null) setYearId(active.academic_year_id);
  }, [years.data, yearId]);

  const status = useQuery({
    queryKey: ['timetable', domain, uploaded?.timetable_id],
    queryFn: () => api.getTimetable(domain, uploaded!.timetable_id),
    enabled: !!uploaded,
    refetchInterval: (q) => {
      const s = q.state.data?.processing_status;
      return !s || s === 'QUEUED' || s === 'PROCESSING' ? 2000 : false;
    },
  });
  const tt = status.data;
  const done = tt && !['QUEUED', 'PROCESSING'].includes(tt.processing_status);
  useEffect(() => {
    if (done) invalidateTimetableData(qc);
  }, [done, qc]);

  const pick = async () => {
    setError(null);
    const r = await DocumentPicker.getDocumentAsync({ type: MIME, copyToCacheDirectory: true, multiple: false });
    if (r.canceled) return;
    const a = r.assets[0];
    const ext = a.name.toLowerCase().slice(a.name.lastIndexOf('.'));
    if (!EXTENSIONS.includes(ext)) return setError('Choose a PDF, Excel (.xlsx/.xls), CSV, Word (.docx/.doc), JPG or PNG file.');
    if (a.size && a.size > MAX_MB * 1024 * 1024) return setError(`Files must be at most ${MAX_MB} MB.`);
    setFile({ uri: a.uri, name: a.name, size: a.size, mimeType: a.mimeType, file: (a as any).file });
    if (!title) setTitle(a.name.replace(/\.[^.]+$/, ''));
    requestId.current = newRequestId(); // new file → new idempotency key; retries of the same file reuse it
  };

  const upload = async () => {
    if (!file) return;
    if (domain === 'INSTITUTIONAL' && !yearId) return setError('Choose the academic year.');
    setBusy(true);
    setError(null);
    try {
      const res = await api.uploadTimetable({
        domain,
        file,
        title: title.trim() || undefined,
        academic_year_id: yearId ?? undefined,
        department_id: deptId ?? undefined,
        client_request_id: requestId.current,
      });
      setUploaded(res);
    } catch (e) {
      const err = e as ApiError;
      setError(err.isNetwork ? `${err.message} You can retry safely — the same upload will not be duplicated.` : err.message);
    } finally {
      setBusy(false);
    }
  };

  if (uploaded) {
    const s = tt?.processing_status ?? uploaded.processing_status;
    const steps = [
      { label: 'Uploaded & stored privately', done: true },
      { label: 'Extracting & validating', done: !!done, active: !done },
      { label: s === 'FAILED' || s === 'UNUSABLE' ? 'Not usable' : 'Ready for review', done: !!done, bad: s === 'FAILED' || s === 'UNUSABLE' },
    ];
    const summary = tt?.validation_summary;
    return (
      <Screen edges={[]}>
        <Spacer />
        <Card>
          <Text variant="heading">{uploaded.title}</Text>
          <Text variant="caption" muted>
            {uploaded.original_filename} · {uploaded.file_format}
          </Text>
          <Spacer />
          {steps.map((st) => (
            <Row key={st.label} gap={10} style={{ minHeight: 34 }}>
              <Ionicons
                name={st.bad ? 'close-circle' : st.done ? 'checkmark-circle' : st.active ? 'sync-circle' : 'ellipse-outline'}
                size={22}
                color={st.bad ? t.colors.danger : st.done ? t.colors.success : st.active ? t.colors.info : t.colors.textFaint}
              />
              <Text>{st.label}</Text>
            </Row>
          ))}
          <Spacer h={6} />
          <StatusPill status={s} />
        </Card>
        {uploaded.warnings?.map((w) => (
          <View key={w.code} style={{ marginTop: 10 }}>
            <Banner tone="info" title={w.message} />
          </View>
        ))}
        {done && summary ? (
          <>
            <SectionHeader title="Validation summary" />
            <Card>
              <Text>{summary.status_reason}</Text>
              <Spacer h={8} />
              <Row wrap gap={6}>
                <Pill tone="neutral" label={`${summary.pages_parsed ?? 0}/${summary.page_count ?? 0} pages parsed`} />
                <Pill tone="success" label={`${summary.by_status?.VERIFIED ?? 0} verified`} />
                <Pill tone="warning" label={`${summary.by_status?.UNVERIFIED ?? 0} unverified`} />
                <Pill tone="danger" label={`${summary.by_status?.INCOMPLETE ?? 0} incomplete`} />
                {summary.tentative_sections ? <Pill tone="warning" label={`${summary.tentative_sections} tentative section(s)`} /> : null}
                {summary.pages_ocr ? <Pill tone="info" label={`${summary.pages_ocr} OCR page(s)`} /> : null}
              </Row>
            </Card>
          </>
        ) : null}
        {s === 'FAILED' ? <Banner tone="danger" title="Processing failed" body={summary?.status_reason ?? 'The file could not be read.'} /> : null}
        <Spacer h={16} />
        <Button title="Open timetable" icon="open-outline" onPress={() => router.replace({ pathname: '/timetable/[id]', params: { id: uploaded.timetable_id, domain } })} />
        <Spacer h={8} />
        <Text variant="caption" faint style={{ textAlign: 'center' }}>
          Uploading never changes your primary timetable. You can make it primary from the timetable page.
        </Text>
      </Screen>
    );
  }

  return (
    <Screen edges={[]}>
      <Spacer />
      <Pill tone={domain === 'PERSONAL' ? 'personal' : 'primary'} icon={domain === 'PERSONAL' ? 'person' : 'school'} label={domain === 'PERSONAL' ? 'Personal (private to you)' : 'Official college timetable'} />
      <Spacer />
      {!online ? <Banner tone="warning" icon="cloud-offline-outline" title="You're offline" body="Uploading needs a connection." /> : null}
      {error ? <Banner tone="danger" icon="alert-circle" title={error} /> : null}
      <Spacer />
      {file ? (
        <Card>
          <Row gap={12}>
            <Ionicons name="document-attach-outline" size={28} color={t.colors.primary} />
            <View style={{ flex: 1 }}>
              <Text variant="bodyStrong" numberOfLines={1}>
                {file.name}
              </Text>
              <Text variant="caption" muted>
                {file.size ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : ''}
              </Text>
            </View>
            <Button small variant="ghost" title="Change" onPress={pick} />
          </Row>
        </Card>
      ) : (
        <Card onPress={pick} style={{ alignItems: 'center', paddingVertical: 32, borderStyle: 'dashed', borderWidth: 1.5, borderColor: t.colors.primary }}>
          <EmptyState icon="cloud-upload-outline" title="Choose a timetable file" body={`PDF, Excel, CSV, Word, JPG or PNG · up to ${MAX_MB} MB`} />
        </Card>
      )}
      <Spacer />
      <TextField label="Title" value={title} onChangeText={setTitle} maxLength={200} placeholder="e.g. Semester 3 timetable" />
      {domain === 'INSTITUTIONAL' ? (
        <>
          <Text variant="caption" muted>
            Academic year
          </Text>
          <Row wrap gap={8} style={{ marginVertical: 8 }}>
            {years.data?.items.map((y: any) => (
              <Chip key={y.academic_year_id} label={`${y.label}${y.status === 'ACTIVE' ? ' (active)' : ''}`} selected={yearId === y.academic_year_id} onPress={() => setYearId(y.academic_year_id)} />
            ))}
          </Row>
          <Text variant="caption" muted>
            Department (used to link batches and courses)
          </Text>
          <Row wrap gap={8} style={{ marginVertical: 8 }}>
            <Chip label="College-wide" selected={deptId === null} onPress={() => setDeptId(null)} />
            {depts.data?.items.map((d: any) => (
              <Chip key={d.department_id} label={d.code} selected={deptId === d.department_id} onPress={() => setDeptId(d.department_id)} />
            ))}
          </Row>
        </>
      ) : null}
      <Spacer />
      <Button title={busy ? 'Uploading…' : 'Upload & process'} icon="arrow-up-circle-outline" onPress={upload} loading={busy} disabled={!file || !online} />
      <Spacer h={10} />
      <Text variant="caption" faint>
        The file is stored privately and processed on the server. Every entry keeps its source page and raw text; uncertain values are flagged for review, never guessed.
      </Text>
    </Screen>
  );
}
