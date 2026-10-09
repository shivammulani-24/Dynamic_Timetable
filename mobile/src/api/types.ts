/** Typed API models mirroring the backend contract (docs/02-api.md). */

export type Domain = 'INSTITUTIONAL' | 'PERSONAL';
export type Role = 'STUDENT' | 'PROFESSOR' | 'HOD' | 'PRINCIPAL' | 'ADMIN';
export type ProcessingStatus = 'QUEUED' | 'PROCESSING' | 'NEEDS_REVIEW' | 'READY' | 'FAILED' | 'UNUSABLE';
export type VerificationStatus = 'VERIFIED' | 'UNVERIFIED' | 'INCOMPLETE' | 'REJECTED';
export type SelectionMode = 'REMEMBER_LAST' | 'ALWAYS_USE_PRIMARY';

/** Stable application status codes — the app branches on these, never on message text. */
export type StatusCode =
  | 'OK'
  | 'NO_MATCH'
  | 'DATA_UNVERIFIED'
  | 'INVALID_REQUEST'
  | 'UNAUTHENTICATED'
  | 'ACCESS_DENIED'
  | 'TIMETABLE_NOT_FOUND'
  | 'NOT_FOUND'
  | 'PRIMARY_SELECTION_CONFLICT'
  | 'CONFLICT'
  | 'CLARIFICATION_REQUIRED'
  | 'UNSUPPORTED_INTENT'
  | 'NO_TIMETABLE_SELECTED'
  | 'TIMETABLE_UNUSABLE'
  | 'TIMETABLE_NOT_READY'
  | 'UNSUPPORTED_FILE'
  | 'FILE_TOO_LARGE'
  | 'RATE_LIMITED'
  | 'INTERNAL_ERROR'
  | 'NETWORK_ERROR'
  | 'TIMEOUT';

export interface TokenPair {
  access_token: string;
  access_expires_at: string;
  refresh_token: string;
  token_type: 'bearer';
}

export interface Placement {
  history_id: string;
  academic_year: string | null;
  academic_year_id: number;
  year_of_study: number;
  semester: number | null;
  department_id: number;
  department: string | null;
  batch_id: number | null;
  batch: string | null;
  status: string;
  effective_from: string;
  effective_to: string | null;
  confirmed_at: string | null;
  note: string | null;
}

export interface Me {
  user_id: string;
  email: string;
  display_name: string;
  timezone: string;
  roles: Role[];
  student: null | {
    student_id: string;
    uid: string | null;
    status: string | null;
    placement: Placement | null;
    batch_codes: string[];
    setup_required: boolean;
  };
  staff: null | { staff_id: string; department_id: number | null; department: string | null };
  institution: { name: string | null; week_start_day: number | null; lunch_boundary: string | null };
}

export interface Preferences {
  timezone: string;
  selection_mode: SelectionMode;
  last_active_domain: Domain | null;
  personal_primary_timetable_id: string | null;
  last_personal_timetable_id: string | null;
  last_institutional_timetable_id: string | null;
  notify_official_timetable: boolean;
  notify_processing: boolean;
  search_history_enabled: boolean;
  theme: 'system' | 'light' | 'dark';
  time_format_24h: boolean;
}

export interface Timetable {
  timetable_id: string;
  domain: Domain;
  title: string;
  original_filename: string;
  file_format: string;
  uploaded_at: string;
  processing_status: ProcessingStatus;
  is_primary: boolean;
  page_count: number | null;
  parser_version: string | null;
  effective_from: string | null;
  effective_from_raw: string | null;
  term_label: string | null;
  data_version: number;
  primary_eligible: boolean;
  academic_year?: string | null;
  academic_year_id?: number;
  department?: string | null;
  validation_summary?: ValidationSummary;
  selection_type?: 'PRIMARY' | 'EXPLICIT_ARCHIVE';
}

export interface ValidationSummary {
  status_reason?: string;
  page_count?: number;
  pages_parsed?: number;
  pages_ocr?: number;
  pages_failed?: number;
  pages?: { page: number; method: string; status: string; ocr_mean_confidence?: number | null }[];
  sections?: { key: number; page: number; title: string | null; program_level: string | null; divisions: string[]; is_tentative: boolean }[];
  class_entries?: number;
  usable_class_entries?: number;
  by_status?: Partial<Record<VerificationStatus, number>>;
  issue_counts?: Record<string, number>;
  tentative_sections?: number;
  time_uncertain_entries?: number;
  upload_warnings?: { code: string; message: string }[];
  error_code?: string;
  confidence_note?: string;
}

export interface TimetableDetail extends Timetable {
  sections: { section_id: string; page: number | null; title: string | null; program_level: string | null; divisions: string[]; is_tentative: boolean; extraction_method: string }[];
  job: Job | null;
}

export interface Job {
  job_id: string;
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  domain?: Domain;
  timetable_id?: string;
}

export interface Warning {
  code: string;
  message: string;
}

export interface Entry {
  entry_id: string;
  kind: 'CLASS' | 'BREAK' | 'ACTIVITY';
  day_of_week: number | null;
  day_name: string | null;
  date: string | null;
  start_time: string | null;
  end_time: string | null;
  duration_minutes: number | null;
  course: string | null;
  course_code: string | null;
  professor: string | null;
  professor_code: string | null;
  batch: string | null;
  room: string | null;
  floor: string | null;
  verification_status: VerificationStatus;
  time_uncertain: boolean;
  is_tentative: boolean;
  confidence: number | null;
  is_corrected: boolean;
  warnings: Warning[];
  source_page: number | null;
  status?: 'IN_PROGRESS' | 'UPCOMING' | 'ENDED';
  minutes_until?: number;
  details_withheld?: boolean;
  raw_text?: string | null;
  time_label_raw?: string | null;
  extraction_method?: string;
  section?: { title: string | null; program_level: string | null; divisions: string[]; is_tentative: boolean } | string | null;
  raw_labels?: { course: string | null; professor: string | null; batch: string | null; room: string | null };
  all_messages?: { severity: string; code: string; message: string }[];
}

export interface Paged<T> {
  items: T[];
  pagination: { limit: number; total: number; next_cursor: string | null };
}

export interface ClarificationChoice {
  label: string;
  value: Record<string, unknown> | null;
}

export interface Clarification {
  kind: 'AMPM' | 'DATE' | 'DATE_RANGE' | 'ENTITY_CHOICE' | 'MISSING_PARAMETER' | 'CONFIRMATION' | 'SETUP_REQUIRED' | 'CONFIGURATION' | 'SELECT_ARCHIVE';
  question: string;
  parameter: string | null;
  choices: ClarificationChoice[];
}

export interface SearchContextInfo {
  domain: Domain;
  selection_type?: 'PRIMARY' | 'EXPLICIT_ARCHIVE';
  timetable_id?: string;
  timetable_title?: string;
  processing_status?: ProcessingStatus;
  timezone?: string;
  now?: string;
}

export type ResultType =
  | 'ENTRIES'
  | 'ENTRY_DETAILS'
  | 'COURSES'
  | 'PROFESSORS'
  | 'FREE_INTERVALS'
  | 'ROOMS'
  | 'ROOM_STATUS'
  | 'SCHEDULE_STATUS'
  | 'SCHEDULED_LOCATION'
  | 'TIMETABLE'
  | 'TIMETABLES'
  | 'ACTION';

export interface SearchResponse {
  status: StatusCode;
  intent: string | null;
  intent_id: string | null;
  context: SearchContextInfo | null;
  message: string;
  clarification: Clarification | null;
  warnings: Warning[];
  result_type: ResultType | null;
  results: any[];
  pagination: { limit: number; total: number; next_cursor: string | null } | null;
  meta: Record<string, any>;
  details: Record<string, any>;
  request_id: string | null;
}

export interface SearchRequest {
  query?: string;
  intent?: string;
  parameters?: Record<string, unknown>;
  domain?: Domain;
  selection?: { type: 'PRIMARY' | 'EXPLICIT_ARCHIVE'; timetable_id?: string };
}

export interface TimetableContext {
  domain: Domain;
  status: StatusCode;
  message: string | null;
  primary: Timetable | null;
  current: Timetable | null;
  selection_mode: SelectionMode;
  warnings: Warning[];
  institutional_settings_version: number | null;
  timezone: string;
}

export interface DashboardCard {
  status: StatusCode;
  intent: string;
  message: string;
  results: any[];
  warnings: Warning[];
  clarification: Clarification | null;
  result_type: ResultType | null;
  meta: Record<string, any>;
}

export interface Dashboard {
  domain: Domain;
  roles: Role[];
  cards: Record<string, DashboardCard>;
  context_status: StatusCode;
  setup_required?: string | null;
  conflicts?: { total: number; counts: Record<string, number> };
  admin?: {
    users_active: number;
    users_invited: number;
    jobs_pending: number;
    jobs_failed: number;
    institutional_needs_review: number;
    institutional_archives: number;
    active_academic_year: string | null;
    official_default_id: string | null;
  };
  personal_archives?: number;
}

export interface NotificationItem {
  notification_id: string;
  kind: string;
  title: string;
  body: string;
  data: Record<string, string>;
  created_at: string;
  read_at: string | null;
}

export interface Conflict {
  type: 'PROFESSOR_OVERLAP' | 'ROOM_OVERLAP' | 'BATCH_OVERLAP';
  resource: string | null;
  confidence: 'CONFIRMED' | 'POSSIBLE';
  reason: string | null;
  entries: Pick<Entry, 'entry_id' | 'day_of_week' | 'start_time' | 'end_time' | 'course' | 'professor' | 'batch' | 'room' | 'verification_status' | 'source_page'>[];
}

export interface ReviewSummary {
  timetable: Timetable;
  pages_processed: number | null;
  pages: ValidationSummary['pages'];
  sections: ValidationSummary['sections'];
  entry_counts: Partial<Record<VerificationStatus, number>>;
  class_entries: number | null;
  missing_required_fields: Record<string, number>;
  ambiguous_time_labels: number;
  explicit_time_conflicts: number;
  unverified_entries: number;
  incomplete_entries: number;
  duplicate_entries: number;
  tentative_sections: number;
  issue_counts: Record<string, number>;
  usability: { status: ProcessingStatus; reason: string | null; primary_eligible: boolean };
  conflicts?: { total: number; counts: Record<string, number> };
}

export interface Finding {
  finding_id: string;
  severity: string;
  code: string;
  message: string;
  source_page: number | null;
  entry_id: string | null;
}
