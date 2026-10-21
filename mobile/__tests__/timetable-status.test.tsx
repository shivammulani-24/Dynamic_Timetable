import { render } from '@testing-library/react-native';

import { TimetableStatus } from '@/components/timetable';

let mockRoles: string[] = [];
jest.mock('@/state/auth', () => ({ useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => mockRoles.includes(x)) }) }));
jest.mock('@/state/domain', () => ({ useDomain: () => ({ prefs: { time_format_24h: false } }) }));

test('students do not see the official timetable review status', async () => {
  mockRoles = ['STUDENT'];
  const { queryByText } = await render(<TimetableStatus status="NEEDS_REVIEW" domain="INSTITUTIONAL" />);
  expect(queryByText('Needs review')).toBeNull();
});

test('the admin does', async () => {
  mockRoles = ['ADMIN'];
  const { getByText } = await render(<TimetableStatus status="NEEDS_REVIEW" domain="INSTITUTIONAL" />);
  expect(getByText('Needs review')).toBeTruthy();
});

test('owners still see the status of their personal uploads', async () => {
  mockRoles = ['STUDENT'];
  const { getByText } = await render(<TimetableStatus status="NEEDS_REVIEW" domain="PERSONAL" />);
  expect(getByText('Needs review')).toBeTruthy();
});

test('failed timetables are always labelled', async () => {
  mockRoles = ['STUDENT'];
  const { getByText } = await render(<TimetableStatus status="FAILED" domain="INSTITUTIONAL" />);
  expect(getByText(/Failed/)).toBeTruthy();
});
