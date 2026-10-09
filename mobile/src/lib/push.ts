import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as Device from 'expo-device';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import * as api from '@/api/endpoints';

/** Expo Go has no remote-push support (removed on Android since SDK 53); skip it there entirely. */
const IN_EXPO_GO = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

/**
 * Registers this device with Expo's push service so the server can notify users about official
 * timetable activation and processing results even when the app is closed. Requires a physical
 * device, a development/production build (not Expo Go) and an EAS projectId
 * (`extra.eas.projectId`); otherwise it silently does nothing and in-app notifications (fetched
 * from the server) still work. `expo-notifications` is loaded lazily so Expo Go never touches it.
 */
export function usePushRegistration(enabled: boolean): void {
  useEffect(() => {
    if (!enabled || Platform.OS === 'web' || IN_EXPO_GO || !Device.isDevice) return;
    const projectId = (Constants.expoConfig?.extra as any)?.eas?.projectId;
    if (!projectId) return;
    let cancelled = false;
    let remove: (() => void) | undefined;
    (async () => {
      try {
        const Notifications = await import('expo-notifications');
        Notifications.setNotificationHandler({
          handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }),
        });
        const sub = Notifications.addNotificationResponseReceivedListener(() => router.push('/notifications'));
        remove = () => sub.remove();
        if (cancelled) return remove();
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
    return () => {
      cancelled = true;
      remove?.();
    };
  }, [enabled]);
}
