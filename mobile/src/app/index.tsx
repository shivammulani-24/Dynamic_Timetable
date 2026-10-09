import { Redirect } from 'expo-router';
import { View } from 'react-native';

import { Button, EmptyState, LoadingState } from '@/components/ui';
import { useAuth } from '@/state/auth';
import { useTheme } from '@/theme/theme';

export default function Index() {
  const { status, refetchMe, signOut } = useAuth();
  const t = useTheme();
  if (status === 'signedIn') return <Redirect href="/(app)/(tabs)" />;
  if (status === 'signedOut') return <Redirect href="/(auth)/welcome" />;
  return (
    <View style={{ flex: 1, justifyContent: 'center', backgroundColor: t.colors.bg, padding: 24, gap: 12 }}>
      {status === 'error' ? (
        <>
          <EmptyState icon="cloud-offline-outline" title="Can't reach the server" body="Your session is saved. Check your connection and try again." />
          <Button title="Try again" icon="refresh" onPress={refetchMe} />
          <Button title="Sign out" variant="ghost" onPress={signOut} />
        </>
      ) : (
        <LoadingState label="Starting…" />
      )}
    </View>
  );
}
