/**
 * Server base URL from EXPO_PUBLIC_API_URL (Expo inlines EXPO_PUBLIC_* at build time).
 * On a phone, use your computer's LAN address, e.g.
 *   EXPO_PUBLIC_API_URL=http://192.168.1.20:8000 npx expo start
 */
export const DEFAULT_API_URL = "http://localhost:8000";

export function apiUrl(): string {
  return (process.env.EXPO_PUBLIC_API_URL || DEFAULT_API_URL).replace(/\/$/, "");
}
