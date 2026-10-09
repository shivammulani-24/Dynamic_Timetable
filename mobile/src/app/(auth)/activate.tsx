import { zodResolver } from '@hookform/resolvers/zod';
import { router } from 'expo-router';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { KeyboardAvoidingView, Platform } from 'react-native';
import { z } from 'zod';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import { Banner, Button, Screen, Spacer, Text, TextField } from '@/components/ui';
import { passwordRule } from '@/lib/validation';
import { useAuth } from '@/state/auth';

const schema = z
  .object({ token: z.string().trim().min(10, 'Paste the activation code from your invitation.'), password: passwordRule, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Passwords do not match.' });
type Form = z.infer<typeof schema>;

export default function Activate() {
  const { acceptTokens } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { control, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { token: '', password: '', confirm: '' } });
  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      await acceptTokens(await api.activate(v.token, v.password, tz));
      router.replace('/(app)/(tabs)');
    } catch (e) {
      setError((e as ApiError).message);
    }
  });
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen edges={[]}>
        <Text variant="display" accessibilityRole="header">
          Activate account
        </Text>
        <Text muted>Your Admin office sends an activation code when your account is created. Roles are assigned by the college, not chosen here.</Text>
        <Spacer h={24} />
        {error ? <Banner tone="danger" icon="alert-circle" title={error} /> : null}
        <Spacer />
        <Controller control={control} name="token" render={({ field }) => (
          <TextField label="Activation code" autoCapitalize="none" autoCorrect={false} value={field.value} onChangeText={field.onChange} error={formState.errors.token?.message} />
        )} />
        <Controller control={control} name="password" render={({ field }) => (
          <TextField label="New password" secureTextEntry textContentType="newPassword" value={field.value} onChangeText={field.onChange} error={formState.errors.password?.message} hint="At least 10 characters with a letter and a number." />
        )} />
        <Controller control={control} name="confirm" render={({ field }) => (
          <TextField label="Confirm password" secureTextEntry textContentType="newPassword" value={field.value} onChangeText={field.onChange} error={formState.errors.confirm?.message} />
        )} />
        <Text variant="caption" faint>
          Your timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone}) will be saved; you can change it later in Settings.
        </Text>
        <Spacer />
        <Button title="Activate and sign in" onPress={submit} loading={formState.isSubmitting} />
      </Screen>
    </KeyboardAvoidingView>
  );
}
