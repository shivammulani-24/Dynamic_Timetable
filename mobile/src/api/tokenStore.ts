import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * Android/iOS: credentials live only in the platform keystore (iOS Keychain / Android Keystore
 * via SecureStore).
 * Web (laptop browser): kept in sessionStorage, so a page refresh keeps you signed in but closing
 * the tab signs you out; nothing is written to long-lived localStorage. Browsers give web pages no
 * keystore, so treat the web version as a convenience for trusted computers.
 */
const KEY = 'tt.session.v1';
let memory: Session | null = null;

export interface Session {
  accessToken: string;
  refreshToken: string;
  accessExpiresAt: string;
}

function webStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' && window.sessionStorage ? window.sessionStorage : null;
  } catch {
    return null; // storage disabled (privacy mode / blocked site data)
  }
}

export async function loadSession(): Promise<Session | null> {
  if (Platform.OS === 'web') {
    if (!memory) {
      try {
        const raw = webStorage()?.getItem(KEY);
        memory = raw ? (JSON.parse(raw) as Session) : null;
      } catch {
        memory = null;
      }
    }
    return memory;
  }
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
  if (Platform.OS === 'web') {
    try {
      webStorage()?.setItem(KEY, JSON.stringify(s));
    } catch {
      // storage unavailable: the session still works until the page is refreshed
    }
    return;
  }
  await SecureStore.setItemAsync(KEY, JSON.stringify(s), {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
  });
}

export async function clearSession(): Promise<void> {
  memory = null;
  if (Platform.OS === 'web') {
    try {
      webStorage()?.removeItem(KEY);
    } catch {
      // nothing to delete
    }
    return;
  }
  try {
    await SecureStore.deleteItemAsync(KEY);
  } catch {
    // nothing to delete
  }
}

export function currentSession(): Session | null {
  return memory;
}
