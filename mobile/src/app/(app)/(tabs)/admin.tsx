import { router, type Href } from 'expo-router';
import { View } from 'react-native';

import { Card, Divider, EmptyState, ListRow, Screen, SectionHeader, Spacer, Text, type IconName } from '@/components/ui';
import { useAuth } from '@/state/auth';
import { useDomain } from '@/state/domain';

type Item = { icon: IconName; title: string; subtitle: string; href: Href };

const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: 'Official timetable',
    items: [
      { icon: 'cloud-upload-outline', title: 'Upload official timetable', subtitle: 'PDF, Excel, Word or image — processed in the background', href: { pathname: '/upload', params: { domain: 'INSTITUTIONAL' } } },
      { icon: 'albums-outline', title: 'Review & activate', subtitle: 'Validation summary, corrections, conflicts, activation', href: '/(app)/(tabs)/archives' },
      { icon: 'git-compare-outline', title: 'Conflict detection', subtitle: 'Professor, room and batch overlaps', href: '/conflicts' },
      { icon: 'pulse-outline', title: 'Processing jobs', subtitle: 'Queued, running and failed extractions', href: '/admin/jobs' },
    ],
  },
  {
    title: 'People',
    items: [
      { icon: 'people-outline', title: 'Users & roles', subtitle: 'Search, roles, account status, re-invite', href: '/admin/users' },
      { icon: 'person-add-outline', title: 'Register student or staff', subtitle: 'Freshers and new staff (invitation based)', href: '/admin/new-user' },
      { icon: 'trending-up-outline', title: 'Academic promotion', subtitle: 'Review and confirm year transitions', href: '/admin/promotion' },
    ],
  },
  {
    title: 'Master data',
    items: [
      { icon: 'business-outline', title: 'Departments', subtitle: 'Codes and names', href: { pathname: '/admin/master/[kind]', params: { kind: 'departments' } } },
      { icon: 'calendar-number-outline', title: 'Academic years', subtitle: 'One active year at a time', href: { pathname: '/admin/master/[kind]', params: { kind: 'academic-years' } } },
      { icon: 'grid-outline', title: 'Batches & lab groups', subtitle: 'Divisions and sub-groups', href: { pathname: '/admin/master/[kind]', params: { kind: 'batches' } } },
      { icon: 'book-outline', title: 'Courses', subtitle: 'Course codes and names', href: { pathname: '/admin/master/[kind]', params: { kind: 'courses' } } },
      { icon: 'location-outline', title: 'Rooms', subtitle: 'Room inventory and floors (needed for free-room search)', href: { pathname: '/admin/master/[kind]', params: { kind: 'rooms' } } },
      { icon: 'swap-horizontal-outline', title: 'Aliases', subtitle: 'Abbreviations used in timetables (e.g. KKD → staff)', href: { pathname: '/admin/master/[kind]', params: { kind: 'aliases' } } },
      { icon: 'settings-outline', title: 'Institution settings', subtitle: 'Week start, lunch boundary, working hours', href: '/admin/config' },
    ],
  },
  { title: 'Oversight', items: [{ icon: 'document-text-outline', title: 'Audit log', subtitle: 'Sensitive actions and access denials', href: '/admin/audit' }] },
];

export default function AdminHub() {
  const { hasRole } = useAuth();
  const { setDomain } = useDomain();
  if (!hasRole('ADMIN')) return <Screen><EmptyState icon="lock-closed-outline" title="Admins only" /></Screen>;
  return (
    <Screen>
      <Spacer h={8} />
      <Text variant="title" accessibilityRole="header">
        Admin
      </Text>
      <Text variant="caption" muted>
        Personal timetables are private to their owners and are not accessible from here.
      </Text>
      {GROUPS.map((g) => (
        <Card key={g.title} style={{ marginTop: 16, paddingVertical: 4 }}>
          <SectionHeader title={g.title} />
          {g.items.map((it, i) => (
            <View key={it.title}>
              {i ? <Divider /> : null}
              <ListRow
                icon={it.icon}
                title={it.title}
                subtitle={it.subtitle}
                onPress={() => {
                  if (it.title === 'Review & activate') setDomain('INSTITUTIONAL');
                  router.push(it.href);
                }}
              />
            </View>
          ))}
        </Card>
      ))}
    </Screen>
  );
}
