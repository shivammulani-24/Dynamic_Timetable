import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { forwardRef, type ComponentProps, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text as RNText,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { useTheme } from '@/theme/theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];

// ------------------------------------------------------------------ text
type Variant = 'display' | 'title' | 'heading' | 'body' | 'bodyStrong' | 'caption' | 'micro';
export function Text({
  variant = 'body',
  color,
  muted,
  faint,
  style,
  ...rest
}: TextProps & { variant?: Variant; color?: string; muted?: boolean; faint?: boolean }) {
  const t = useTheme();
  const c = color ?? (faint ? t.colors.textFaint : muted ? t.colors.textMuted : t.colors.text);
  return <RNText maxFontSizeMultiplier={1.6} style={[t.type[variant], { color: c }, style]} {...rest} />;
}

// ------------------------------------------------------------------ layout
export function Screen({
  children,
  scroll = true,
  refreshing,
  onRefresh,
  edges = ['top'],
  padded = true,
  contentStyle,
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  edges?: Edge[];
  padded?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
}) {
  const t = useTheme();
  const pad = padded ? { paddingHorizontal: t.spacing.lg, paddingBottom: t.spacing.xxxl } : null;
  return (
    <SafeAreaView edges={edges} style={{ flex: 1, backgroundColor: t.colors.bg }}>
      {scroll ? (
        <ScrollView
          contentContainerStyle={[pad, contentStyle]}
          keyboardShouldPersistTaps="handled"
          refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={t.colors.primary} /> : undefined}
        >
          {children}
        </ScrollView>
      ) : (
        <View style={[{ flex: 1 }, pad, contentStyle]}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Card({ children, style, onPress, accessibilityLabel }: { children: ReactNode; style?: StyleProp<ViewStyle>; onPress?: () => void; accessibilityLabel?: string }) {
  const t = useTheme();
  const base: ViewStyle = {
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.lg,
    padding: t.spacing.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.colors.border,
    ...(t.dark
      ? {}
      : Platform.select<ViewStyle>({
          ios: { shadowColor: '#0F172A', shadowOpacity: 0.06, shadowRadius: 10, shadowOffset: { width: 0, height: 3 } },
          android: { elevation: 1 },
          default: {},
        })),
  };
  if (!onPress) return <View style={[base, style]}>{children}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      onPress={onPress}
      style={({ pressed }) => [base, { opacity: pressed ? 0.85 : 1, transform: [{ scale: pressed ? 0.99 : 1 }] }, style]}
    >
      {children}
    </Pressable>
  );
}

export function Row({ children, gap = 8, style, wrap }: { children: ReactNode; gap?: number; style?: StyleProp<ViewStyle>; wrap?: boolean }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap, flexWrap: wrap ? 'wrap' : 'nowrap' }, style]}>{children}</View>;
}

export function Spacer({ h = 12 }: { h?: number }) {
  return <View style={{ height: h }} />;
}

export function SectionHeader({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  const t = useTheme();
  return (
    <Row style={{ justifyContent: 'space-between', marginTop: t.spacing.xl, marginBottom: t.spacing.sm }}>
      <Text variant="heading" accessibilityRole="header">
        {title}
      </Text>
      {action && onAction ? (
        <Pressable onPress={onAction} hitSlop={10} accessibilityRole="button">
          <Text variant="caption" color={t.colors.primary}>
            {action}
          </Text>
        </Pressable>
      ) : null}
    </Row>
  );
}

// ------------------------------------------------------------------ buttons
export function Button({
  title,
  onPress,
  variant = 'primary',
  icon,
  loading,
  disabled,
  small,
  style,
  accessibilityHint,
  label,
}: {
  title: string;
  /** Accessible name; required when `title` is empty (icon-only button). */
  label?: string;
  onPress?: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityHint?: string;
}) {
  const t = useTheme();
  const bg = { primary: t.colors.primary, secondary: t.colors.primarySoft, ghost: 'transparent', danger: t.colors.danger }[variant];
  const fg = { primary: t.colors.primaryText, secondary: t.colors.primary, ghost: t.colors.primary, danger: '#fff' }[variant];
  const off = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label ?? title}
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      accessibilityHint={accessibilityHint}
      disabled={off}
      onPress={() => {
        if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => undefined);
        onPress?.();
      }}
      style={({ pressed }) => [
        {
          minHeight: small ? 38 : 50,
          paddingHorizontal: small ? 14 : 18,
          borderRadius: t.radius.md,
          backgroundColor: bg,
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'row',
          gap: 8,
          opacity: off ? 0.5 : pressed ? 0.85 : 1,
        },
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={fg} /> : icon ? <Ionicons name={icon} size={small ? 16 : 18} color={fg} /> : null}
      {title ? (
        <Text variant={small ? 'caption' : 'bodyStrong'} color={fg}>
          {title}
        </Text>
      ) : null}
    </Pressable>
  );
}

export function IconButton({ icon, onPress, label, color }: { icon: IconName; onPress: () => void; label: string; color?: string }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={8}
      style={({ pressed }) => ({ width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: pressed ? t.colors.surfaceAlt : 'transparent' })}
    >
      <Ionicons name={icon} size={22} color={color ?? t.colors.text} />
    </Pressable>
  );
}

export function Chip({ label, selected, onPress, icon }: { label: string; selected?: boolean; onPress?: () => void; icon?: IconName }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingHorizontal: 14,
        minHeight: 36,
        borderRadius: t.radius.pill,
        backgroundColor: selected ? t.colors.primary : t.colors.surface,
        borderWidth: 1,
        borderColor: selected ? t.colors.primary : t.colors.border,
        opacity: pressed ? 0.8 : 1,
      })}
    >
      {icon ? <Ionicons name={icon} size={14} color={selected ? t.colors.primaryText : t.colors.textMuted} /> : null}
      <Text variant="caption" color={selected ? t.colors.primaryText : t.colors.text}>
        {label}
      </Text>
    </Pressable>
  );
}

// ------------------------------------------------------------------ status
type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'primary' | 'personal';
export function Pill({ label, tone = 'neutral', icon }: { label: string; tone?: Tone; icon?: IconName }) {
  const t = useTheme();
  const map: Record<Tone, [string, string]> = {
    success: [t.colors.successSoft, t.colors.success],
    warning: [t.colors.warningSoft, t.colors.warning],
    danger: [t.colors.dangerSoft, t.colors.danger],
    info: [t.colors.infoSoft, t.colors.info],
    neutral: [t.colors.surfaceAlt, t.colors.textMuted],
    primary: [t.colors.primarySoft, t.colors.primary],
    personal: [t.colors.personalSoft, t.colors.personal],
  };
  const [bg, fg] = map[tone];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: bg, paddingHorizontal: 8, paddingVertical: 3, borderRadius: t.radius.pill, alignSelf: 'flex-start' }}>
      {icon ? <Ionicons name={icon} size={12} color={fg} /> : null}
      <Text variant="micro" color={fg}>
        {label}
      </Text>
    </View>
  );
}

const STATUS_TONE: Record<string, [Tone, IconName, string]> = {
  VERIFIED: ['success', 'checkmark-circle', 'Verified'],
  UNVERIFIED: ['warning', 'alert-circle', 'Unverified'],
  INCOMPLETE: ['danger', 'remove-circle', 'Incomplete'],
  REJECTED: ['neutral', 'close-circle', 'Rejected'],
  READY: ['success', 'checkmark-done', 'Ready'],
  NEEDS_REVIEW: ['warning', 'eye', 'Needs review'],
  QUEUED: ['info', 'time', 'Queued'],
  PROCESSING: ['info', 'sync', 'Processing'],
  FAILED: ['danger', 'close-circle', 'Failed'],
  UNUSABLE: ['danger', 'ban', 'Unusable'],
  ACTIVE: ['success', 'checkmark-circle', 'Active'],
  INVITED: ['info', 'mail', 'Invited'],
  SUSPENDED: ['warning', 'pause-circle', 'Suspended'],
  DISABLED: ['danger', 'ban', 'Disabled'],
};
export function StatusPill({ status }: { status: string }) {
  const [tone, icon, label] = STATUS_TONE[status] ?? ['neutral', 'ellipse', status];
  return <Pill tone={tone} icon={icon} label={label} />;
}

export function Banner({ tone = 'info', icon, title, body, action, onAction }: { tone?: Tone; icon?: IconName; title: string; body?: string; action?: string; onAction?: () => void }) {
  const t = useTheme();
  const colors: Record<Tone, [string, string]> = {
    success: [t.colors.successSoft, t.colors.success],
    warning: [t.colors.warningSoft, t.colors.warning],
    danger: [t.colors.dangerSoft, t.colors.danger],
    info: [t.colors.infoSoft, t.colors.info],
    neutral: [t.colors.surfaceAlt, t.colors.textMuted],
    primary: [t.colors.primarySoft, t.colors.primary],
    personal: [t.colors.personalSoft, t.colors.personal],
  };
  const [bg, fg] = colors[tone];
  return (
    <View accessibilityRole="summary" style={{ backgroundColor: bg, borderRadius: t.radius.md, padding: t.spacing.md, flexDirection: 'row', gap: 10 }}>
      <Ionicons name={icon ?? 'information-circle'} size={20} color={fg} style={{ marginTop: 1 }} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="bodyStrong" color={fg}>
          {title}
        </Text>
        {body ? <Text variant="caption" muted>{body}</Text> : null}
        {action && onAction ? (
          <Pressable onPress={onAction} accessibilityRole="button" style={{ marginTop: 6 }}>
            <Text variant="caption" color={fg} style={{ textDecorationLine: 'underline' }}>
              {action}
            </Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

export function EmptyState({ icon = 'calendar-clear-outline', title, body, action, onAction }: { icon?: IconName; title: string; body?: string; action?: string; onAction?: () => void }) {
  const t = useTheme();
  return (
    <View style={{ alignItems: 'center', paddingVertical: t.spacing.xxl, paddingHorizontal: t.spacing.lg, gap: 8 }}>
      <View style={{ width: 64, height: 64, borderRadius: 32, backgroundColor: t.colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
        <Ionicons name={icon} size={30} color={t.colors.primary} />
      </View>
      <Text variant="heading" style={{ textAlign: 'center' }}>
        {title}
      </Text>
      {body ? (
        <Text muted style={{ textAlign: 'center' }}>
          {body}
        </Text>
      ) : null}
      {action && onAction ? <Button title={action} onPress={onAction} variant="secondary" small style={{ marginTop: 8 }} /> : null}
    </View>
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  const t = useTheme();
  return (
    <View style={{ paddingVertical: t.spacing.xxl, alignItems: 'center', gap: 10 }} accessibilityLiveRegion="polite">
      <ActivityIndicator color={t.colors.primary} />
      <Text muted variant="caption">
        {label}
      </Text>
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error as { message?: string; code?: string; requestId?: string | null; isNetwork?: boolean };
  return (
    <EmptyState
      icon={e?.isNetwork ? 'cloud-offline-outline' : 'warning-outline'}
      title={e?.isNetwork ? 'You appear to be offline' : 'Something went wrong'}
      body={`${e?.message ?? 'Unexpected error.'}${e?.requestId ? `\nRef: ${e.requestId}` : ''}`}
      action={onRetry ? 'Try again' : undefined}
      onAction={onRetry}
    />
  );
}

// ------------------------------------------------------------------ inputs
export const TextField = forwardRef<TextInput, TextInputProps & { label: string; error?: string; hint?: string }>(function TextField(
  { label, error, hint, style, ...rest },
  ref,
) {
  const t = useTheme();
  return (
    <View style={{ gap: 6, marginBottom: t.spacing.md }}>
      <Text variant="caption" muted>
        {label}
      </Text>
      <TextInput
        ref={ref}
        accessibilityLabel={label}
        placeholderTextColor={t.colors.textFaint}
        maxFontSizeMultiplier={1.6}
        style={[
          {
            minHeight: 50,
            borderRadius: t.radius.md,
            borderWidth: 1,
            borderColor: error ? t.colors.danger : t.colors.border,
            backgroundColor: t.colors.surface,
            paddingHorizontal: 14,
            color: t.colors.text,
            fontSize: 16,
          } as TextStyle,
          style,
        ]}
        {...rest}
      />
      {error ? (
        <Text variant="caption" color={t.colors.danger} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : hint ? (
        <Text variant="caption" faint>
          {hint}
        </Text>
      ) : null}
    </View>
  );
});

export function Segmented<T extends string>({ options, value, onChange, tones }: { options: { value: T; label: string; icon?: IconName }[]; value: T; onChange: (v: T) => void; tones?: Partial<Record<T, string>> }) {
  const t = useTheme();
  return (
    <View accessibilityRole="tablist" style={{ flexDirection: 'row', backgroundColor: t.colors.surfaceAlt, borderRadius: t.radius.md, padding: 4, gap: 4 }}>
      {options.map((o) => {
        const sel = o.value === value;
        const tone = tones?.[o.value] ?? t.colors.primary;
        return (
          <Pressable
            key={o.value}
            accessibilityRole="tab"
            accessibilityState={{ selected: sel }}
            onPress={() => onChange(o.value)}
            style={{ flex: 1, minHeight: 40, borderRadius: t.radius.sm, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6, backgroundColor: sel ? t.colors.surface : 'transparent' }}
          >
            {o.icon ? <Ionicons name={o.icon} size={16} color={sel ? tone : t.colors.textMuted} /> : null}
            <Text variant="caption" color={sel ? tone : t.colors.textMuted}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function ListRow({ icon, title, subtitle, right, onPress, tone }: { icon?: IconName; title: string; subtitle?: string; right?: ReactNode; onPress?: () => void; tone?: string }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingVertical: 10, opacity: pressed ? 0.7 : 1 })}
    >
      {icon ? (
        <View style={{ width: 36, height: 36, borderRadius: 10, backgroundColor: t.colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={icon} size={18} color={tone ?? t.colors.primary} />
        </View>
      ) : null}
      <View style={{ flex: 1 }}>
        <Text variant="bodyStrong">{title}</Text>
        {subtitle ? (
          <Text variant="caption" muted numberOfLines={2}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {right ?? (onPress ? <Ionicons name="chevron-forward" size={18} color={t.colors.textFaint} /> : null)}
    </Pressable>
  );
}

export function Divider() {
  const t = useTheme();
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: t.colors.border }} />;
}

export function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  const t = useTheme();
  return (
    <View style={{ flex: 1, minWidth: 130, backgroundColor: t.colors.surface, borderRadius: t.radius.md, padding: t.spacing.md, borderWidth: StyleSheet.hairlineWidth, borderColor: t.colors.border }}>
      <Text variant="title" color={tone}>
        {value}
      </Text>
      <Text variant="caption" muted>
        {label}
      </Text>
    </View>
  );
}
