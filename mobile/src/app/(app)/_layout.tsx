import { Redirect, Stack } from 'expo-router';

import { LoadingState } from '@/components/ui';
import { usePushRegistration } from '@/lib/push';
import { useAuth } from '@/state/auth';
import { useTheme } from '@/theme/theme';

export default function AppLayout() {
  const { status } = useAuth();
  const t = useTheme();
  usePushRegistration(status === 'signedIn');
  if (status === 'signedOut') return <Redirect href="/(auth)/welcome" />;
  if (status !== 'signedIn') return <LoadingState />;
  return (
    <Stack
      screenOptions={{
        headerShadowVisible: false,
        headerStyle: { backgroundColor: t.colors.bg },
        headerTintColor: t.colors.text,
        headerTitleStyle: { fontWeight: '600' },
        contentStyle: { backgroundColor: t.colors.bg },
        headerBackButtonDisplayMode: 'minimal',
      }}
    >
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="class/[entryId]" options={{ title: 'Class details' }} />
      <Stack.Screen name="timetable/[id]" options={{ title: 'Timetable' }} />
      <Stack.Screen name="review/[id]" options={{ title: 'Review extraction' }} />
      <Stack.Screen name="upload" options={{ title: 'Upload timetable', presentation: 'modal' }} />
      <Stack.Screen name="notifications" options={{ title: 'Notifications' }} />
      <Stack.Screen name="conflicts" options={{ title: 'Conflicts' }} />
      <Stack.Screen name="monitor" options={{ title: 'Monitoring' }} />
      <Stack.Screen name="password" options={{ title: 'Change password' }} />
      <Stack.Screen name="admin/users" options={{ title: 'Users' }} />
      <Stack.Screen name="admin/user/[id]" options={{ title: 'User' }} />
      <Stack.Screen name="admin/new-user" options={{ title: 'Register user', presentation: 'modal' }} />
      <Stack.Screen name="admin/master/[kind]" options={{ title: 'Master data' }} />
      <Stack.Screen name="admin/config" options={{ title: 'Institution settings' }} />
      <Stack.Screen name="admin/promotion" options={{ title: 'Academic promotion' }} />
      <Stack.Screen name="admin/jobs" options={{ title: 'Processing jobs' }} />
      <Stack.Screen name="admin/audit" options={{ title: 'Audit log' }} />
    </Stack>
  );
}
