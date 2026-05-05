import { api } from '@/api/client';

export interface LoginResponse {
  access_token: string;
  token_type?: string;
  expires_at: string;
  /** Backend uses `label` for human name, `kid` for the numeric key id. */
  label?: string | null;
  kid?: number | null;
  /** Legacy field names used by Stage 1 stub. */
  key_id?: number | null;
}

export interface MeResponse {
  label: string;
  kid: number;
  issued_at?: string;
  expires_at: string;
}

export interface AdminKey {
  id: number;
  label: string | null;
  created_at: string;
  revoked_at: string | null;
  valid_until: string | null;
  is_active?: boolean;
}

export interface RotateRequest {
  /** Backend prefers `new_label`; we keep `grace` for UI parity (always implied 3h). */
  new_label?: string | null;
}

export interface RotateResponse {
  new_plaintext_key: string;
  new_key_id: number;
  new_label: string;
  previous_key_id: number | null;
  previous_valid_until: string | null;
  access_token: string;
  expires_at: string;
}

export const authApi = {
  login: (key: string) => api.post<LoginResponse>('/admin/auth/login', { key }),
  me: () => api.get<MeResponse>('/admin/auth/me'),
  listKeys: () => api.get<AdminKey[]>('/admin/auth/keys'),
  rotateKey: (payload: RotateRequest) =>
    api.post<RotateResponse>('/admin/auth/refresh', payload),
  revokeKey: (id: number) => api.delete<{ ok: boolean }>(`/admin/auth/keys/${id}`),
};

// Legacy named exports kept for back-compat with existing imports:
export const login = authApi.login;
export const getMe = authApi.me;
export const listKeys = authApi.listKeys;
export const rotateKey = authApi.rotateKey;
export const revokeKey = authApi.revokeKey;
