import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import type { ReactNode } from 'react';
import { Platform, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AuthProvider } from '@/state/auth';
import { DomainProvider, useDomain } from '@/state/domain';
import { persister, queryClient, shouldPersist } from '@/state/query';
import { ThemeProvider, useTheme } from '@/theme/theme';

function Themed({ children }: { children: ReactNode }) {
  const { prefs } = useDomain();
  return <ThemeProvider pref={prefs?.theme ?? 'system'}>{children}</ThemeProvider>;
}

/** Max width of the app column in a laptop/desktop browser; phones are unaffected. */
const WEB_MAX_WIDTH = 760;

function Nav() {
  const t = useTheme();
  const nav = (
    <>
      <StatusBar style={t.dark ? 'light' : 'dark'} />
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
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="(auth)" options={{ headerShown: false }} />
        <Stack.Screen name="(app)" options={{ headerShown: false }} />
      </Stack>
    </>
  );
  if (Platform.OS !== 'web') return nav;
  // On a wide screen, show the app as a centred column instead of stretching it edge to edge.
  return (
    <View style={{ flex: 1, backgroundColor: t.dark ? '#020617' : '#E2E8F0' }}>
      <View
        style={{
          flex: 1,
          width: '100%',
          maxWidth: WEB_MAX_WIDTH,
          alignSelf: 'center',
          backgroundColor: t.colors.bg,
          borderLeftWidth: 1,
          borderRightWidth: 1,
          borderColor: t.colors.border,
        }}
      >
        {nav}
      </View>
    </View>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <PersistQueryClientProvider
          client={queryClient}
          persistOptions={{ persister, maxAge: 7 * 24 * 3600 * 1000, dehydrateOptions: { shouldDehydrateQuery: shouldPersist } }}
        >
          <AuthProvider>
            <DomainProvider>
              <Themed>
                <Nav />
              </Themed>
            </DomainProvider>
          </AuthProvider>
        </PersistQueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
