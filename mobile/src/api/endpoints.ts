import { Platform } from 'react-native';

import { UPLOAD_TIMEOUT_MS } from '@/lib/config';

import { request } from './client';
import type {
  Conflict,
  Dashboard,
  Domain,
  Entry,
  Finding,
  Job,
  Me,
  NotificationItem,
  Paged,
  Preferences,
  ReviewSummary,
  Role,
  SearchRequest,
  SearchResponse,
  Timetable,
  TimetableContext,
  TimetableDetail,
  TokenPair,
} from './types';

// ---------------------------------------------------------------- auth
export const login = (email: string, password: string) =>
  request<TokenPair>('/auth/login', { method: 'POST', auth: false, body: { email, password, device_label: Platform.OS } });
export const logout = (refresh_token?: string) => request('/auth/logout', { method: 'POST', body: { refresh_token } });
export const activate = (token: string, password: string, timezone?: string) =>
  request<TokenPair>('/auth/activate', { method: 'POST', auth: false, body: { token, password, timezone } });
export const requestReset = (email: string) =>
  request<{ message: string; dev_reset_token?: string }>('/auth/password-reset/request', { method: 'POST', auth: false, body: { email } });
export const confirmReset = (token: string, password: string) =>
  request('/auth/password-reset/confirm', { method: 'POST', auth: false, body: { token, password } });
export const changePassword = (current_password: string, new_password: string) =>
  request('/auth/change-password', { method: 'POST', body: { current_password, new_password } });

// ---------------------------------------------------------------- me
export const getMe = () => request<Me>('/me');
export const getPreferences = () => request<Preferences>('/me/preferences');
export const patchPreferences = (p: Partial<Preferences>) => request<Preferences>('/me/preferences', { method: 'PATCH', body: p });
export const setSelection = (domain: Domain, timetable_id: string | null) =>
  request('/me/selection', { method: 'PUT', body: { domain, timetable_id } });
export const registerPush = (expo_push_token: string, platform: 'ios' | 'android' | 'web') =>
  request('/me/push-devices', { method: 'POST', body: { expo_push_token, platform } });

// ---------------------------------------------------------------- timetables
export const getContext = (domain: Domain) => request<TimetableContext>('/timetable-context', { query: { domain } });
export const listTimetables = (domain: Domain, cursor?: string) =>
  request<Paged<Timetable>>('/timetables', { query: { domain, limit: 25, cursor } });
export const getTimetable = (domain: Domain, id: string) => request<TimetableDetail>(`/timetables/${id}`, { query: { domain } });
export const listEntries = (
  domain: Domain,
  id: string,
  q: { day_of_week?: number; needs_review?: boolean; review?: boolean; status?: string; cursor?: string; limit?: number } = {},
) => request<Paged<Entry> & { data_version: number }>(`/timetables/${id}/entries`, { query: { domain, limit: q.limit ?? 100, ...q } });
export const getFindings = (domain: Domain, id: string) => request<Paged<Finding>>(`/timetables/${id}/findings`, { query: { domain, limit: 100 } });
export const getReviewSummary = (domain: Domain, id: string) => request<ReviewSummary>(`/timetables/${id}/review-summary`, { query: { domain } });
export const makePrimary = (domain: Domain, id: string) =>
  request<{ domain: Domain; primary_timetable_id: string }>(`/timetables/${id}/make-primary`, { method: 'POST', query: { domain } });
export const reprocess = (domain: Domain, id: string) => request<Job>(`/timetables/${id}/reprocess`, { method: 'POST', query: { domain } });
export const removeTimetable = (domain: Domain, id: string) => request(`/timetables/${id}`, { method: 'DELETE', query: { domain } });
export const correctEntry = (domain: Domain, id: string, entryId: string, changes: Record<string, unknown>) =>
  request<Entry>(`/timetables/${id}/entries/${entryId}`, { method: 'PATCH', query: { domain }, body: changes });
export const bulkReview = (domain: Domain, id: string, entry_ids: string[], verification_status: 'VERIFIED' | 'REJECTED') =>
  request<{ updated: number; skipped: { entry_id: string; reason: string }[] }>(`/timetables/${id}/entries/bulk-review`, {
    method: 'POST',
    query: { domain },
    body: { entry_ids, verification_status },
  });
export const getConflicts = (id: string) =>
  request<{ total: number; counts: Record<string, number>; conflicts: Conflict[]; entries_considered: number; note: string }>(
    `/timetables/${id}/conflicts`,
  );
export const listJobs = () => request<Paged<Job>>('/jobs', { query: { limit: 50 } });

export interface UploadFile {
  uri: string;
  name: string;
  mimeType?: string | null;
  file?: File; // web
}
export function uploadTimetable(args: {
  domain: Domain;
  file: UploadFile;
  title?: string;
  academic_year_id?: number;
  department_id?: number;
  client_request_id: string;
}) {
  const fd = new FormData();
  fd.append('domain', args.domain);
  if (args.title) fd.append('title', args.title);
  if (args.academic_year_id) fd.append('academic_year_id', String(args.academic_year_id));
  if (args.department_id) fd.append('department_id', String(args.department_id));
  fd.append('client_request_id', args.client_request_id);
  if (Platform.OS === 'web' && args.file.file) {
    fd.append('file', args.file.file, args.file.name);
  } else {
    // React Native FormData file part
    fd.append('file', { uri: args.file.uri, name: args.file.name, type: args.file.mimeType ?? 'application/octet-stream' } as any);
  }
  return request<Timetable & { created: boolean; job_id: string | null; warnings: { code: string; message: string }[] }>(
    '/timetables/uploads',
    { method: 'POST', form: fd, timeoutMs: UPLOAD_TIMEOUT_MS },
  );
}

// ---------------------------------------------------------------- search
export const search = (body: SearchRequest) => request<SearchResponse>('/search', { method: 'POST', body, envelope: true });
export const getDashboard = (domain: Domain) => request<Dashboard>('/dashboard', { query: { domain } });
export const getHistory = () =>
  request<Paged<{ search_id: string; query: string; intent: string | null; status: string; domain: Domain; created_at: string }>>(
    '/search/history',
    { query: { limit: 15 } },
  );
export const clearHistory = () => request('/search/history', { method: 'DELETE' });
export const listSaved = () =>
  request<{ items: { saved_search_id: string; name: string; query: string | null; intent: string | null; parameters: Record<string, unknown> }[] }>(
    '/saved-searches',
  );
export const saveSearch = (name: string, query?: string, intent?: string, parameters?: Record<string, unknown>) =>
  request<{ saved_search_id: string }>('/saved-searches', { method: 'POST', body: { name, query, intent, parameters } });
export const deleteSaved = (id: string) => request(`/saved-searches/${id}`, { method: 'DELETE' });

// ---------------------------------------------------------------- notifications
export const listNotifications = () => request<Paged<NotificationItem> & { unread: number }>('/notifications', { query: { limit: 50 } });
export const unreadCount = () => request<{ unread: number }>('/notifications/unread-count');
export const markRead = (id: string) => request(`/notifications/${id}/read`, { method: 'POST' });
export const markAllRead = () => request('/notifications/read-all', { method: 'POST' });

// ---------------------------------------------------------------- admin
export interface AdminUser {
  user_id: string;
  email: string;
  display_name: string;
  account_status: string;
  roles: Role[];
  student_id: string | null;
  uid: string | null;
  student_status: string | null;
  staff_id: string | null;
  staff_department_id: number | null;
  short_code: string | null;
  last_login_at: string | null;
  academic_history?: any[];
}
export const adminUsers = (q: { q?: string; role?: string; status?: string; cursor?: string }) =>
  request<Paged<AdminUser>>('/admin/users', { query: { limit: 30, ...q } });
export const adminUser = (id: string) => request<AdminUser>(`/admin/users/${id}`);
export const adminSetRoles = (id: string, roles: Role[]) => request(`/admin/users/${id}/roles`, { method: 'PUT', body: { roles } });
export const adminSetStatus = (id: string, account_status: string) => request(`/admin/users/${id}/status`, { method: 'PUT', body: { account_status } });
export const adminReinvite = (id: string) => request<{ dev_invitation_token?: string }>(`/admin/users/${id}/reinvite`, { method: 'POST' });
export const adminCreateStudent = (body: Record<string, unknown>) =>
  request<{ user_id: string; dev_invitation_token?: string; invitation_email_sent: boolean }>('/admin/students', { method: 'POST', body });
export const adminCreateStaff = (body: Record<string, unknown>) =>
  request<{ user_id: string; dev_invitation_token?: string; invitation_email_sent: boolean }>('/admin/staff', { method: 'POST', body });

export type MasterKind = 'departments' | 'academic-years' | 'batches' | 'courses' | 'rooms' | 'aliases';
export const adminList = <T = any>(kind: MasterKind) => request<{ items: T[] }>(`/admin/${kind}`);
export const adminCreate = (kind: MasterKind, body: Record<string, unknown>) => request(`/admin/${kind}`, { method: 'POST', body });
export const adminUpdate = (kind: MasterKind, id: string | number, body: Record<string, unknown>) =>
  request(`/admin/${kind}/${id}`, { method: 'PUT', body });
export const adminDeleteAlias = (id: number) => request(`/admin/aliases/${id}`, { method: 'DELETE' });
export const adminConfig = () => request<Record<string, any>>('/admin/config');
export const adminPutConfig = (body: Record<string, unknown>) => request('/admin/config', { method: 'PUT', body });
export const adminEligible = (q: { batch_id?: number; academic_year_id?: number }) =>
  request<Paged<{ student_id: string; uid: string; name: string; student_status: string; current: any }>>('/admin/students/eligible', {
    query: { limit: 100, ...q },
  });
export const adminPromotionPreview = (items: Record<string, unknown>[]) =>
  request<{ items: any[]; errors: { student_id: string; message: string }[]; can_confirm: boolean }>('/admin/promotions/preview', {
    method: 'POST',
    body: { items },
  });
export const adminPromotionConfirm = (items: Record<string, unknown>[]) =>
  request<{ confirmed: number }>('/admin/promotions/confirm', { method: 'POST', body: { items } });
export const adminAudit = (cursor?: string) => request<Paged<any>>('/admin/audit', { query: { limit: 40, cursor } });
export const adminRemap = (id: string) => request<{ changed_entries: number }>(`/admin/timetables/${id}/remap`, { method: 'POST' });
