import { zodResolver } from '@hookform/resolvers/zod';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { KeyboardAvoidingView, Platform, type TextInput } from 'react-native';
import { z } from 'zod';

import { ApiError } from '@/api/client';
import { Banner, Button, Screen, Spacer, Text, TextField } from '@/components/ui';
import { useAuth } from '@/state/auth';

const schema = z.object({
  email: z.string().trim().email('Enter your college email address.'),
  password: z.string().min(1, 'Enter your password.'),
});
type Form = z.infer<typeof schema>;

export default function Login() {
  const { signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const pwRef = useRef<TextInput>(null);
  const { control, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { email: '', password: '' } });

  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      await signIn(v.email, v.password);
      router.replace('/(app)/(tabs)');
    } catch (e) {
      const err = e as ApiError;
      setError(
        err.code === 'RATE_LIMITED'
          ? 'Too many attempts. Please wait a minute and try again.'
          : err.isNetwork
            ? 'Cannot reach the server. Check your connection.'
            : err.message,
      );
    }
  });

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen edges={[]}>
        <Text variant="display" accessibilityRole="header">
          Sign in
        </Text>
        <Text muted>Use the college email address the Admin office registered for you.</Text>
        <Spacer h={24} />
        {error ? (
          <>
            <Banner tone="danger" icon="alert-circle" title={error} />
            <Spacer />
          </>
        ) : null}
        <Controller
          control={control}
          name="email"
          render={({ field }) => (
            <TextField
              label="College email"
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              textContentType="username"
              returnKeyType="next"
              onSubmitEditing={() => pwRef.current?.focus()}
              value={field.value}
              onChangeText={field.onChange}
              onBlur={field.onBlur}
              error={formState.errors.email?.message}
            />
          )}
        />
        <Controller
          control={control}
          name="password"
          render={({ field }) => (
            <TextField
              ref={pwRef}
              label="Password"
              secureTextEntry
              autoComplete="password"
              textContentType="password"
              returnKeyType="go"
              onSubmitEditing={submit}
              value={field.value}
              onChangeText={field.onChange}
              onBlur={field.onBlur}
              error={formState.errors.password?.message}
            />
          )}
        />
        <Button title="Sign in" onPress={submit} loading={formState.isSubmitting} />
        <Spacer />
        <Button title="Forgot password?" variant="ghost" onPress={() => router.push('/(auth)/forgot')} />
        <Button title="Activate a new account" variant="ghost" onPress={() => router.push('/(auth)/activate')} />
      </Screen>
    </KeyboardAvoidingView>
  );
}
