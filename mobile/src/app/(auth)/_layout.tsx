import { Redirect, Stack } from 'expo-router';

import { useAuth } from '@/state/auth';
import { useTheme } from '@/theme/theme';

export default function AuthLayout() {
  const { status } = useAuth();
  const t = useTheme();
  if (status === 'signedIn') return <Redirect href="/(app)/(tabs)" />;
  return (
    <Stack
      screenOptions={{
        headerShadowVisible: false,
        headerStyle: { backgroundColor: t.colors.bg },
        headerTintColor: t.colors.text,
        headerTitle: '',
        contentStyle: { backgroundColor: t.colors.bg },
      }}
    >
      <Stack.Screen name="welcome" options={{ headerShown: false }} />
    </Stack>
  );
}
