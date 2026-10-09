import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Text } from '@/components/ui';
import { useAuth } from '@/state/auth';
import { useTheme } from '@/theme/theme';

const FEATURES: { icon: keyof typeof Ionicons.glyphMap; title: string; body: string }[] = [
  { icon: 'flash-outline', title: 'Your day at a glance', body: 'Current class, next class and time remaining.' },
  { icon: 'chatbubble-ellipses-outline', title: 'Ask in plain English', body: '“Is room 508 free at 2 PM today?”' },
  { icon: 'documents-outline', title: 'Official & personal views', body: 'Kept strictly separate — never mixed.' },
];

export default function Welcome() {
  const t = useTheme();
  const { expiredNotice } = useAuth();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.colors.bg }}>
      <View style={{ flex: 1, padding: 24, justifyContent: 'space-between' }}>
        <View style={{ gap: 28, marginTop: 24 }}>
          <View style={{ width: 64, height: 64, borderRadius: 20, backgroundColor: t.colors.primary, alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons name="calendar" size={32} color={t.colors.primaryText} />
          </View>
          <View style={{ gap: 8 }}>
            <Text variant="display" accessibilityRole="header">
              Your timetable,{'\n'}always current.
            </Text>
            <Text muted>Sign in with your college email to see your schedule, find rooms and ask questions.</Text>
          </View>
          <View style={{ gap: 18 }}>
            {FEATURES.map((f) => (
              <View key={f.title} style={{ flexDirection: 'row', gap: 14 }}>
                <View style={{ width: 40, height: 40, borderRadius: 12, backgroundColor: t.colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
                  <Ionicons name={f.icon} size={20} color={t.colors.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text variant="bodyStrong">{f.title}</Text>
                  <Text variant="caption" muted>
                    {f.body}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        </View>
        <View style={{ gap: 10 }}>
          {expiredNotice ? (
            <Text variant="caption" color={t.colors.warning} style={{ textAlign: 'center' }}>
              Your session ended. Please sign in again.
            </Text>
          ) : null}
          <Button title="Sign in" onPress={() => router.push('/(auth)/login')} />
          <Button title="I have an activation code" variant="ghost" onPress={() => router.push('/(auth)/activate')} />
        </View>
      </View>
    </SafeAreaView>
  );
}
