import { fireEvent, render } from '@testing-library/react-native';

import type { SearchResponse } from '@/api/types';
import { SearchResult } from '@/components/results';

jest.mock('@/state/domain', () => ({ useDomain: () => ({ prefs: { time_format_24h: false } }) }));

const base: SearchResponse = {
  status: 'OK', intent: 'NEXT_CLASS', intent_id: 'Q10', context: { domain: 'INSTITUTIONAL', timetable_id: 't1' },
  message: 'Your next class is DBMS', clarification: null, warnings: [], result_type: 'ENTRIES', results: [], pagination: null,
  meta: {}, details: {}, request_id: null,
};
const entry = {
  entry_id: 'e1', kind: 'CLASS', day_of_week: 1, day_name: 'Monday', date: '2026-10-12', start_time: '10:00', end_time: '11:00',
  duration_minutes: 60, course: 'Data Structures (Lab)', course_code: 'DS Lab', professor: 'Prof. Anita V. Nair', professor_code: 'AVN',
  batch: 'SE-A1', room: '604', floor: '6', verification_status: 'UNVERIFIED', time_uncertain: true, is_tentative: false, confidence: 0.6,
  is_corrected: false, warnings: [], source_page: 1,
};

test('clarification choices send their typed value back', async () => {
  const onChoose = jest.fn();
  const res: SearchResponse = {
    ...base, status: 'CLARIFICATION_REQUIRED', message: 'Did you mean 2:00 AM or 2:00 PM?',
    clarification: { kind: 'AMPM', question: 'Did you mean 2:00 AM or 2:00 PM?', parameter: 'time',
      choices: [{ label: '2:00 PM', value: { time: '14:00' } }, { label: '2:00 AM', value: { time: '02:00' } }] },
  };
  const { getByText } = await render(<SearchResult res={res} onChoose={onChoose} />);
  await fireEvent.press(getByText('2:00 PM'));
  expect(onChoose).toHaveBeenCalledWith({ time: '14:00' });
});

test('unverified entries are visibly marked, never shown as confirmed', async () => {
  const { getByText, getAllByText } = await render(
    <SearchResult res={{ ...base, status: 'DATA_UNVERIFIED', results: [entry] }} onChoose={jest.fn()} />,
  );
  expect(getByText('Includes unverified data')).toBeTruthy();
  expect(getAllByText('Unverified').length).toBeGreaterThan(0);
  expect(getByText('Time unverified')).toBeTruthy();
  expect(getByText('Data Structures (Lab)')).toBeTruthy();
});

test('NO_MATCH explains no broader search happened', async () => {
  const { getByText } = await render(<SearchResult res={{ ...base, status: 'NO_MATCH', message: 'No classes found' }} onChoose={jest.fn()} />);
  expect(getByText(/never pulled from another timetable/)).toBeTruthy();
});

test('unsupported cross-domain request renders an explanation', async () => {
  const { getByText } = await render(
    <SearchResult res={{ ...base, status: 'UNSUPPORTED_INTENT', intent: 'CROSS_DOMAIN_COMPARE', message: "Comparing isn't supported" }} onChoose={jest.fn()} />,
  );
  expect(getByText('Not supported')).toBeTruthy();
});

test('a slot without faculty or room shows just the course (e.g. LLC)', async () => {
  const llc = { ...entry, entry_id: 'e2', course: 'Co Curricular Course', course_code: 'LLC', professor: null, professor_code: null,
    room: null, floor: null, verification_status: 'VERIFIED', time_uncertain: false };
  const { getByText, queryByText } = await render(<SearchResult res={{ ...base, results: [llc] }} onChoose={jest.fn()} />);
  expect(getByText('Co Curricular Course')).toBeTruthy();
  expect(getByText('LLC')).toBeTruthy();                       // printed code shown under the name
  expect(queryByText(/Not given/)).toBeNull();
  expect(queryByText('Unverified')).toBeNull();
});
