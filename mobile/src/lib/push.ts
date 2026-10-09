import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import * as api from '@/api/endpoints';

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }),
});

/**
 * Registers this device with Expo's push service so the server can notify users about official
 * timetable activation and processing results even when the app is closed. Requires a physical
 * device and an EAS projectId (`extra.eas.projectId`); otherwise it silently does nothing and
 * in-app notifications (fetched from the server) still work.
 */
export function usePushRegistration(enabled: boolean): void {
  useEffect(() => {
    if (!enabled || Platform.OS === 'web' || !Device.isDevice) return;
    const projectId = (Constants.expoConfig?.extra as any)?.eas?.projectId;
    if (!projectId) return;
    let cancelled = false;
    (async () => {
      try {
        let { status } = await Notifications.getPermissionsAsync();
        if (status !== 'granted') status = (await Notifications.requestPermissionsAsync()).status;
        if (status !== 'granted' || cancelled) return;
        if (Platform.OS === 'android') {
          await Notifications.setNotificationChannelAsync('default', { name: 'Timetable updates', importance: Notifications.AndroidImportance.DEFAULT });
        }
        const token = await Notifications.getExpoPushTokenAsync({ projectId });
        if (!cancelled) await api.registerPush(token.data, Platform.OS === 'ios' ? 'ios' : 'android');
      } catch {
        // push is optional; never block the app
      }
    })();
    const sub = Notifications.addNotificationResponseReceivedListener(() => router.push('/notifications'));
    return () => {
      cancelled = true;
      sub.remove();
    };
  }, [enabled]);
}
