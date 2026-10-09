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

const emailSchema = z.object({ email: z.string().trim().email('Enter your college email address.') });
const resetSchema = z.object({ token: z.string().trim().min(10, 'Enter the reset code.'), password: passwordRule });

export default function Forgot() {
  const [step, setStep] = useState<'email' | 'code' | 'done'>('email');
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const emailForm = useForm<z.infer<typeof emailSchema>>({ resolver: zodResolver(emailSchema), defaultValues: { email: '' } });
  const resetForm = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema), defaultValues: { token: '', password: '' } });

  const sendCode = emailForm.handleSubmit(async (v) => {
    setError(null);
    try {
      const r = await api.requestReset(v.email);
      // dev_reset_token is only returned by non-production servers without SMTP (development convenience).
      if (r.dev_reset_token) resetForm.setValue('token', r.dev_reset_token);
      setInfo(r.message + (r.dev_reset_token ? ' (Development server: code pre-filled.)' : ''));
      setStep('code');
    } catch (e) {
      setError((e as ApiError).message);
    }
  });
  const reset = resetForm.handleSubmit(async (v) => {
    setError(null);
    try {
      await api.confirmReset(v.token, v.password);
      setStep('done');
    } catch (e) {
      setError((e as ApiError).message);
    }
  });

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen edges={[]}>
        <Text variant="display" accessibilityRole="header">
          Reset password
        </Text>
        <Spacer h={16} />
        {error ? <Banner tone="danger" icon="alert-circle" title={error} /> : null}
        {info && step === 'code' ? <Banner tone="info" title={info} /> : null}
        <Spacer />
        {step === 'email' ? (
          <>
            <Controller control={emailForm.control} name="email" render={({ field }) => (
              <TextField label="College email" autoCapitalize="none" keyboardType="email-address" value={field.value} onChangeText={field.onChange} error={emailForm.formState.errors.email?.message} />
            )} />
            <Button title="Send reset code" onPress={sendCode} loading={emailForm.formState.isSubmitting} />
          </>
        ) : step === 'code' ? (
          <>
            <Controller control={resetForm.control} name="token" render={({ field }) => (
              <TextField label="Reset code" autoCapitalize="none" value={field.value} onChangeText={field.onChange} error={resetForm.formState.errors.token?.message} />
            )} />
            <Controller control={resetForm.control} name="password" render={({ field }) => (
              <TextField label="New password" secureTextEntry value={field.value} onChangeText={field.onChange} error={resetForm.formState.errors.password?.message} />
            )} />
            <Button title="Set new password" onPress={reset} loading={resetForm.formState.isSubmitting} />
          </>
        ) : (
          <>
            <Banner tone="success" icon="checkmark-circle" title="Password updated" body="All other sessions were signed out." />
            <Spacer />
            <Button title="Back to sign in" onPress={() => router.replace('/(auth)/login')} />
          </>
        )}
      </Screen>
    </KeyboardAvoidingView>
  );
}
