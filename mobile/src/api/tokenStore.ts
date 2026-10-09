import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * Credentials live only in the platform keystore (iOS Keychain / Android Keystore via SecureStore).
 * On web (development preview only) they are kept in memory for the tab's lifetime.
 */
const KEY = 'tt.session.v1';
let memory: Session | null = null;

export interface Session {
  accessToken: string;
  refreshToken: string;
  accessExpiresAt: string;
}

export async function loadSession(): Promise<Session | null> {
  if (Platform.OS === 'web') return memory;
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    memory = raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    memory = null;
  }
  return memory;
}

export async function saveSession(s: Session): Promise<void> {
  memory = s;
  if (Platform.OS !== 'web') {
    await SecureStore.setItemAsync(KEY, JSON.stringify(s), {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    });
  }
}

export async function clearSession(): Promise<void> {
  memory = null;
  if (Platform.OS !== 'web') {
    try {
      await SecureStore.deleteItemAsync(KEY);
    } catch {
      // nothing to delete
    }
  }
}

export function currentSession(): Session | null {
  return memory;
}
