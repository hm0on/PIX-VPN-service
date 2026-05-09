import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios';
import { toast } from 'sonner';

import { config } from '@/config';
import { uuidv4 } from '@/lib/utils';
import { useAuthStore } from '@/stores/authStore';

export const apiClient: AxiosInstance = axios.create({
  baseURL: config.apiBaseUrl,
  timeout: 20_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((reqConfig: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().token;
  if (token) {
    reqConfig.headers.set('Authorization', `Bearer ${token}`);
  }
  reqConfig.headers.set('X-Trace-ID', uuidv4());
  return reqConfig;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status;
    if (status === 401) {
      const { logout, token } = useAuthStore.getState();
      if (token) {
        logout();
        if (typeof window !== 'undefined') {
          // Учитываем base path (slug админки) — BASE_URL заканчивается на "/"
          const base = import.meta.env.BASE_URL || '/';
          const loginPath = `${base.replace(/\/$/, '')}/login`;
          if (window.location.pathname !== loginPath) {
            window.location.replace(loginPath);
          }
        }
      }
    } else if (status === 403) {
      toast.error('Нет доступа к этому действию');
    } else if (status === 429) {
      toast.error('Слишком много запросов. Подождите немного.');
    }
    return Promise.reject(error);
  }
);

export function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: string; message?: string } | undefined;
    if (typeof data?.detail === 'string') return data.detail;
    if (typeof data?.message === 'string') return data.message;
    if (err.response?.status === 401) return 'Неверный admin-ключ';
    if (err.response?.status === 429) return 'Слишком много попыток';
    return err.message ?? 'Ошибка запроса';
  }
  if (err instanceof Error) return err.message;
  return 'Неизвестная ошибка';
}

/* ---- Typed helpers ---- */

export const api = {
  get: <T>(url: string, params?: Record<string, unknown>) =>
    apiClient.get<T>(url, { params }).then((r) => r.data),
  post: <T, B = unknown>(url: string, body?: B) => apiClient.post<T>(url, body).then((r) => r.data),
  put: <T, B = unknown>(url: string, body?: B) =>
    apiClient.put<T>(url, body).then((r) => r.data),
  patch: <T, B = unknown>(url: string, body?: B) =>
    apiClient.patch<T>(url, body).then((r) => r.data),
  delete: <T>(url: string) => apiClient.delete<T>(url).then((r) => r.data),
};
