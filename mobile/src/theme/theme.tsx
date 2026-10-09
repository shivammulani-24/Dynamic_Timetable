import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';

export type ThemePref = 'system' | 'light' | 'dark';

const palette = {
  indigo: { 50: '#EEF2FF', 100: '#E0E7FF', 400: '#818CF8', 500: '#6366F1', 600: '#4F46E5', 700: '#4338CA', 900: '#312E81' },
  slate: { 0: '#FFFFFF', 50: '#F8FAFC', 100: '#F1F5F9', 200: '#E2E8F0', 300: '#CBD5E1', 400: '#94A3B8', 500: '#64748B', 600: '#475569', 700: '#334155', 800: '#1E293B', 850: '#172033', 900: '#0F172A', 950: '#0B1120' },
  green: { 100: '#DCFCE7', 600: '#16A34A', 300: '#86EFAC', 900: '#14532D' },
  amber: { 100: '#FEF3C7', 600: '#D97706', 300: '#FCD34D', 900: '#78350F' },
  red: { 100: '#FEE2E2', 600: '#DC2626', 300: '#FCA5A5', 900: '#7F1D1D' },
  sky: { 100: '#E0F2FE', 600: '#0284C7', 300: '#7DD3FC', 900: '#0C4A6E' },
  teal: { 100: '#CCFBF1', 600: '#0D9488', 300: '#5EEAD4', 900: '#134E4A' },
};

export interface Colors {
  bg: string;
  surface: string;
  surfaceAlt: string;
  border: string;
  text: string;
  textMuted: string;
  textFaint: string;
  primary: string;
  primaryText: string;
  primarySoft: string;
  success: string;
  successSoft: string;
  warning: string;
  warningSoft: string;
  danger: string;
  dangerSoft: string;
  info: string;
  infoSoft: string;
  personal: string;
  personalSoft: string;
  overlay: string;
}

const light: Colors = {
  bg: palette.slate[50],
  surface: palette.slate[0],
  surfaceAlt: palette.slate[100],
  border: palette.slate[200],
  text: palette.slate[900],
  textMuted: palette.slate[600],
  textFaint: palette.slate[400],
  primary: palette.indigo[600],
  primaryText: '#FFFFFF',
  primarySoft: palette.indigo[50],
  success: palette.green[600],
  successSoft: palette.green[100],
  warning: palette.amber[600],
  warningSoft: palette.amber[100],
  danger: palette.red[600],
  dangerSoft: palette.red[100],
  info: palette.sky[600],
  infoSoft: palette.sky[100],
  personal: palette.teal[600],
  personalSoft: palette.teal[100],
  overlay: 'rgba(15,23,42,0.45)',
};

const dark: Colors = {
  bg: palette.slate[950],
  surface: palette.slate[900],
  surfaceAlt: palette.slate[850],
  border: palette.slate[800],
  text: palette.slate[50],
  textMuted: palette.slate[400],
  textFaint: palette.slate[500],
  primary: palette.indigo[400],
  primaryText: palette.slate[950],
  primarySoft: 'rgba(129,140,248,0.14)',
  success: palette.green[300],
  successSoft: 'rgba(22,163,74,0.18)',
  warning: palette.amber[300],
  warningSoft: 'rgba(217,119,6,0.18)',
  danger: palette.red[300],
  dangerSoft: 'rgba(220,38,38,0.18)',
  info: palette.sky[300],
  infoSoft: 'rgba(2,132,199,0.18)',
  personal: palette.teal[300],
  personalSoft: 'rgba(13,148,136,0.18)',
  overlay: 'rgba(0,0,0,0.6)',
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28, xxxl: 40 } as const;
export const radius = { sm: 8, md: 12, lg: 16, xl: 22, pill: 999 } as const;
export const type = {
  display: { fontSize: 28, lineHeight: 34, fontWeight: '700' as const, letterSpacing: -0.4 },
  title: { fontSize: 21, lineHeight: 27, fontWeight: '700' as const, letterSpacing: -0.2 },
  heading: { fontSize: 17, lineHeight: 23, fontWeight: '600' as const },
  body: { fontSize: 15, lineHeight: 21, fontWeight: '400' as const },
  bodyStrong: { fontSize: 15, lineHeight: 21, fontWeight: '600' as const },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: '500' as const },
  micro: { fontSize: 12, lineHeight: 16, fontWeight: '600' as const, letterSpacing: 0.3 },
};

export interface Theme {
  dark: boolean;
  colors: Colors;
  spacing: typeof spacing;
  radius: typeof radius;
  type: typeof type;
}

const ThemeCtx = createContext<Theme>({ dark: false, colors: light, spacing, radius, type });

export function ThemeProvider({ pref = 'system', children }: { pref?: ThemePref; children: ReactNode }) {
  const scheme = useColorScheme();
  const isDark = pref === 'dark' || (pref === 'system' && scheme === 'dark');
  const value = useMemo(() => ({ dark: isDark, colors: isDark ? dark : light, spacing, radius, type }), [isDark]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
