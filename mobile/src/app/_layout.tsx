import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import type { ReactNode } from 'react';
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

function Nav() {
  const t = useTheme();
  return (
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
