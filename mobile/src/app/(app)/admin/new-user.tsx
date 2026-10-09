import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { Role } from '@/api/types';
import { Banner, Button, Chip, Row, Screen, Segmented, Spacer, Text, TextField } from '@/components/ui';

export default function NewUser() {
  const qc = useQueryClient();
  const [kind, setKind] = useState<'student' | 'staff'>('student');
  const [f, setF] = useState({ email: '', name: '', uid: '', year_of_study: '1', semester: '1', effective_from: new Date().toISOString().slice(0, 10), short_code: '', designation: '' });
  const [dept, setDept] = useState<number | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [batch, setBatch] = useState<number | null>(null);
  const [roles, setRoles] = useState<Role[]>(['PROFESSOR']);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string; token?: string } | null>(null);
  const depts = useQuery({ queryKey: ['admin', 'departments'], queryFn: () => api.adminList<any>('departments') });
  const years = useQuery({ queryKey: ['admin', 'academic-years'], queryFn: () => api.adminList<any>('academic-years') });
  const batches = useQuery({ queryKey: ['admin', 'batches'], queryFn: () => api.adminList<any>('batches') });
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });

  const submit = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r =
        kind === 'student'
          ? await api.adminCreateStudent({
              email: f.email.trim(), display_name: f.name.trim(), uid: f.uid.trim(), department_id: dept, academic_year_id: year,
              year_of_study: Number(f.year_of_study), semester: f.semester ? Number(f.semester) : null, batch_id: batch, effective_from: f.effective_from,
            })
          : await api.adminCreateStaff({
              email: f.email.trim(), display_name: f.name.trim(), roles, department_id: dept, short_code: f.short_code || null, designation: f.designation || null,
            });
      setResult({ ok: true, text: r.invitation_email_sent ? 'Invitation emailed.' : 'Account created. Share the activation code securely.', token: r.dev_invitation_token });
      qc.invalidateQueries({ queryKey: ['admin-users'] });
      setF({ ...f, email: '', name: '', uid: '', short_code: '', designation: '' });
    } catch (e) {
      const err = e as ApiError;
      const fields = (err.details?.fields as { field: string; message: string }[] | undefined)?.map((x) => `${x.field}: ${x.message}`).join('\n');
      setResult({ ok: false, text: fields || err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen edges={[]}>
      <Spacer />
      <Segmented value={kind} onChange={setKind} options={[{ value: 'student', label: 'Student (fresher)', icon: 'school-outline' }, { value: 'staff', label: 'Staff', icon: 'briefcase-outline' }]} />
      <Spacer />
      <Text variant="caption" muted>
        {kind === 'student'
          ? 'Use this only for new students. Continuing students keep their identity — use Academic promotion instead.'
          : 'Roles are assigned here by the Admin; users never choose their own role.'}
      </Text>
      <Spacer />
      {result ? <Banner tone={result.ok ? 'success' : 'danger'} title={result.text} body={result.token ? `Development activation code: ${result.token}` : undefined} /> : null}
      <Spacer />
      <TextField label="College email" value={f.email} onChangeText={set('email')} autoCapitalize="none" keyboardType="email-address" />
      <TextField label="Full name" value={f.name} onChangeText={set('name')} />
      <Text variant="caption" muted>Department</Text>
      <Row wrap gap={8} style={{ marginVertical: 8 }}>
        {depts.data?.items.map((d: any) => <Chip key={d.department_id} label={d.code} selected={dept === d.department_id} onPress={() => { setDept(d.department_id); setBatch(null); }} />)}
        {kind === 'staff' ? <Chip label="None" selected={dept === null} onPress={() => setDept(null)} /> : null}
      </Row>
      {kind === 'student' ? (
        <>
          <TextField label="Student UID" value={f.uid} onChangeText={set('uid')} autoCapitalize="characters" />
          <Text variant="caption" muted>Academic year</Text>
          <Row wrap gap={8} style={{ marginVertical: 8 }}>
            {years.data?.items.filter((y: any) => y.status !== 'CLOSED').map((y: any) => <Chip key={y.academic_year_id} label={y.label} selected={year === y.academic_year_id} onPress={() => setYear(y.academic_year_id)} />)}
          </Row>
          <Row gap={8}>
            <View style={{ flex: 1 }}><TextField label="Year of study" value={f.year_of_study} onChangeText={set('year_of_study')} keyboardType="number-pad" /></View>
            <View style={{ flex: 1 }}><TextField label="Semester" value={f.semester} onChangeText={set('semester')} keyboardType="number-pad" /></View>
          </Row>
          <Text variant="caption" muted>Batch (optional)</Text>
          <Row wrap gap={8} style={{ marginVertical: 8 }}>
            <Chip label="Not yet" selected={batch === null} onPress={() => setBatch(null)} />
            {batches.data?.items.filter((b: any) => b.department_id === dept).map((b: any) => <Chip key={b.batch_id} label={b.code} selected={batch === b.batch_id} onPress={() => setBatch(b.batch_id)} />)}
          </Row>
          <TextField label="Effective from (YYYY-MM-DD)" value={f.effective_from} onChangeText={set('effective_from')} />
        </>
      ) : (
        <>
          <Text variant="caption" muted>Roles</Text>
          <Row wrap gap={8} style={{ marginVertical: 8 }}>
            {(['PROFESSOR', 'HOD', 'PRINCIPAL', 'ADMIN'] as Role[]).map((r) => (
              <Chip key={r} label={r} selected={roles.includes(r)} onPress={() => setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r])} />
            ))}
          </Row>
          <TextField label="Timetable code (e.g. KKD)" value={f.short_code} onChangeText={set('short_code')} autoCapitalize="characters" hint="Lets extracted timetables link classes to this person." />
          <TextField label="Designation" value={f.designation} onChangeText={set('designation')} />
        </>
      )}
      <Button title="Create and invite" icon="send-outline" loading={busy} onPress={submit} disabled={!f.email || !f.name || (kind === 'student' && (!dept || !year || !f.uid))} />
    </Screen>
  );
}
