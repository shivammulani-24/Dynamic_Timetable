import Constants from 'expo-constants';
import { Platform } from 'react-native';

/**
 * API base URL resolution (no localhost is baked into production builds):
 * 1. EXPO_PUBLIC_API_URL — set this for every deployed/build environment (must be https in production).
 * 2. Development only: derive the dev machine's LAN IP from the Metro host so Expo Go on a physical
 *    phone, the iOS simulator and the Android emulator reach the backend on port 8000.
 */
export function resolveApiUrl(): string {
  const explicit = process.env.EXPO_PUBLIC_API_URL;
  if (explicit) return explicit.replace(/\/+$/, '');
  if (__DEV__) {
    const hostUri = Constants.expoConfig?.hostUri ?? '';
    const host = hostUri.split(':')[0];
    if (host) return `http://${host}:8000`;
    // Android emulator reaches the host machine via 10.0.2.2
    return Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000';
  }
  throw new Error('EXPO_PUBLIC_API_URL is not configured for this build.');
}

export const API_URL = resolveApiUrl();
export const API_PREFIX = `${API_URL}/api/v1`;
export const REQUEST_TIMEOUT_MS = 20_000;
export const UPLOAD_TIMEOUT_MS = 120_000;
