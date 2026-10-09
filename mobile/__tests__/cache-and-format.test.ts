import { shouldPersist } from '@/state/query';
import { addDaysIso, fmtDuration, fmtRange, fmtTime, isoDow } from '@/lib/format';

const q = (key: unknown[], status = 'success') => ({ queryKey: key, state: { status } }) as any;

test('only institutional, non-personal reads are persisted to device storage', () => {
  expect(shouldPersist(q(['dashboard', 'INSTITUTIONAL']))).toBe(true);
  expect(shouldPersist(q(['entries', 'INSTITUTIONAL', 'tt', 1]))).toBe(true);
  expect(shouldPersist(q(['dashboard', 'PERSONAL']))).toBe(false);
  expect(shouldPersist(q(['entries', 'PERSONAL', 'tt', 1]))).toBe(false);
  expect(shouldPersist(q(['notifications']))).toBe(false);
  expect(shouldPersist(q(['me']))).toBe(false);
  expect(shouldPersist(q(['dashboard', 'INSTITUTIONAL'], 'error'))).toBe(false);
});

test('time formatting', () => {
  expect(fmtTime('14:05')).toBe('2:05 PM');
  expect(fmtTime('00:30')).toBe('12:30 AM');
  expect(fmtTime('12:00')).toBe('12:00 PM');
  expect(fmtTime('09:00', true)).toBe('09:00');
  expect(fmtTime(null)).toBe('—');
  expect(fmtRange('09:00', '10:00')).toBe('9:00 AM – 10:00 AM');
  expect(fmtDuration(90)).toBe('1 h 30 min');
  expect(fmtDuration(45)).toBe('45 min');
});

test('ISO date helpers do not shift across timezones', () => {
  expect(isoDow('2026-10-12')).toBe(1); // Monday
  expect(isoDow('2026-10-18')).toBe(7); // Sunday
  expect(addDaysIso('2026-12-31', 1)).toBe('2027-01-01');
});
