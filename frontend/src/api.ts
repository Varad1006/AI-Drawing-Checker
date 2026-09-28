import axios, { AxiosError } from 'axios';
import type { AIInfo, ChatMessage, ComponentType, Detail, DrawingSummary, Op, RuleInfo } from './types';

const http = axios.create({ baseURL: '/api' });
const k = (key: string) => encodeURIComponent(key);

export function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
    if (!err.response) return 'Cannot reach the backend — is it running on port 8000?';
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

export const api = {
  health: () => http.get<{ status: string; ai: AIInfo }>('/health').then((r) => r.data),
  rules: () => http.get<{ rules: RuleInfo[]; types: ComponentType[] }>('/rules').then((r) => r.data),
  list: () => http.get<DrawingSummary[]>('/drawings').then((r) => r.data),
  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return http.post<DrawingSummary>('/drawings/upload', form).then((r) => r.data);
  },
  demo: () => http.post<DrawingSummary>('/drawings/demo').then((r) => r.data),
  get: (id: number) => http.get<Detail>(`/drawings/${id}`).then((r) => r.data),
  remove: (id: number) => http.delete(`/drawings/${id}`),
  edit: (id: number, ops: Op[], summary?: string) =>
    http.post<Detail>(`/drawings/${id}/edits`, { ops, summary }).then((r) => r.data),
  setHead: (id: number, rev_no: number) => http.post<Detail>(`/drawings/${id}/head`, { rev_no }).then((r) => r.data),
  fix: (id: number, key: string) => http.post<Detail>(`/drawings/${id}/issues/${k(key)}/fix`).then((r) => r.data),
  review: (id: number, key: string, status: string, comment: string) =>
    http.put<Detail>(`/drawings/${id}/issues/${k(key)}/review`, { status, comment }).then((r) => r.data),
  autofix: (id: number) => http.post<Detail>(`/drawings/${id}/autofix`).then((r) => r.data),
  aiReview: (id: number) => http.post(`/drawings/${id}/ai-review`).then((r) => r.data),
  chat: (id: number) => http.get<ChatMessage[]>(`/drawings/${id}/chat`).then((r) => r.data),
  send: (id: number, message: string) =>
    http.post<Detail>(`/drawings/${id}/chat`, { message }).then((r) => r.data),
  exportUrl: (id: number, kind: 'dxf' | 'markup-dxf' | 'report-pdf' | 'original') => `/api/drawings/${id}/export/${kind}`,
};
