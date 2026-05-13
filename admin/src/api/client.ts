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

/**
 * Normalise the backend's flat list-response shape into the meta-wrapped
 * shape every admin page (and every type in ``types/api.ts``) expects.
 *
 * Backend returns ``{items, total, page, page_size}`` (see
 * ``AdminUsersPage`` / ``AdminSubsPage`` / etc.). The frontend type
 * ``Page<T>`` is ``{items, meta: {total, page, per_page, pages}}``.
 *
 * Without this adapter, every paginated page renders the first batch
 * (because ``items`` happens to land on the right key) but then hides
 * the ``<Pagination>`` block because ``meta`` is undefined — which is
 * exactly the symptom that prompted this fix: 50 users visible, no
 * way to reach the 51st.
 *
 * Triggers only when the response body looks like a list page (has
 * ``items`` array + ``total`` number) and lacks a ``meta`` field. Any
 * other shape (single User, raw array endpoints, etc.) is passed
 * through untouched.
 */
function adaptListResponse(data: unknown): unknown {
  if (
    data &&
    typeof data === 'object' &&
    !Array.isArray(data) &&
    Array.isArray((data as Record<string, unknown>).items) &&
    typeof (data as Record<string, unknown>).total === 'number' &&
    (data as Record<string, unknown>).meta === undefined
  ) {
    const flat = data as {
      items: unknown[];
      total: number;
      page?: number;
      page_size?: number;
    };
    const page = flat.page ?? 1;
    const perPage = flat.page_size ?? flat.items.length || 1;
    const pages = perPage > 0 ? Math.max(1, Math.ceil(flat.total / perPage)) : 1;
    return {
      items: flat.items,
      meta: {
        total: flat.total,
        page,
        per_page: perPage,
        pages,
      },
    };
  }
  return data;
}

apiClient.interceptors.response.use(
  (response) => {
    response.data = adaptListResponse(response.data);
    return response;
  },
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
