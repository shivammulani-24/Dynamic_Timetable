import { zodResolver } from '@hookform/resolvers/zod';
import { router } from 'expo-router';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import { Banner, Button, Screen, Spacer, TextField } from '@/components/ui';
import { passwordRule } from '@/lib/validation';
import { useAuth } from '@/state/auth';

const schema = z
  .object({ current: z.string().min(1, 'Enter your current password.'), next: passwordRule, confirm: z.string() })
  .refine((v) => v.next === v.confirm, { path: ['confirm'], message: 'Passwords do not match.' });

export default function ChangePassword() {
  const { signOut } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { control, handleSubmit, formState } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { current: '', next: '', confirm: '' } });
  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      await api.changePassword(v.current, v.next);
      // The server revokes all sessions after a password change, including this one.
      await signOut();
      router.replace('/(auth)/login');
    } catch (e) {
      setError((e as ApiError).message);
    }
  });
  return (
    <Screen edges={[]}>
      <Spacer />
      {error ? <Banner tone="danger" title={error} /> : <Banner tone="info" title="You'll be signed out on all devices after changing your password." />}
      <Spacer />
      <Controller control={control} name="current" render={({ field }) => <TextField label="Current password" secureTextEntry value={field.value} onChangeText={field.onChange} error={formState.errors.current?.message} />} />
      <Controller control={control} name="next" render={({ field }) => <TextField label="New password" secureTextEntry value={field.value} onChangeText={field.onChange} error={formState.errors.next?.message} hint="At least 10 characters with a letter and a number." />} />
      <Controller control={control} name="confirm" render={({ field }) => <TextField label="Confirm new password" secureTextEntry value={field.value} onChangeText={field.onChange} error={formState.errors.confirm?.message} />} />
      <Button title="Change password" onPress={submit} loading={formState.isSubmitting} />
    </Screen>
  );
}
