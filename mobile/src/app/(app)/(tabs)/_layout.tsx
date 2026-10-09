import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import type { ColorValue } from 'react-native';

import { useAuth } from '@/state/auth';
import { useTheme } from '@/theme/theme';

type IconName = keyof typeof Ionicons.glyphMap;

export default function TabsLayout() {
  const t = useTheme();
  const { hasRole } = useAuth();
  const icon = (name: IconName) =>
    function TabIcon({ color, focused }: { color: ColorValue; focused: boolean }) {
      return <Ionicons name={(focused ? name : `${name}-outline`) as IconName} size={23} color={color as string} />;
    };
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: t.colors.primary,
        tabBarInactiveTintColor: t.colors.textFaint,
        tabBarStyle: { backgroundColor: t.colors.surface, borderTopColor: t.colors.border },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: icon('home') }} />
      <Tabs.Screen name="search" options={{ title: 'Ask', tabBarIcon: icon('chatbubble-ellipses') }} />
      <Tabs.Screen name="timetable" options={{ title: 'Timetable', tabBarIcon: icon('calendar') }} />
      <Tabs.Screen name="archives" options={{ title: 'Archives', tabBarIcon: icon('albums') }} />
      {/* Hiding a tab is a convenience only — every admin endpoint is enforced on the server. */}
      <Tabs.Screen name="admin" options={{ title: 'Admin', tabBarIcon: icon('shield'), href: hasRole('ADMIN') ? undefined : null }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile', tabBarIcon: icon('person-circle') }} />
    </Tabs>
  );
}
