import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface AuthState {
  token: string | null;
  expiresAt: string | null;
  label: string | null;
  keyId: number | null;

  login: (payload: {
    token: string;
    expiresAt: string;
    label?: string | null;
    keyId?: number | null;
  }) => void;
  logout: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      expiresAt: null,
      label: null,
      keyId: null,

      login: ({ token, expiresAt, label = null, keyId = null }) =>
        set({ token, expiresAt, label, keyId }),

      logout: () => set({ token: null, expiresAt: null, label: null, keyId: null }),

      isAuthenticated: () => {
        const { token, expiresAt } = get();
        if (!token) return false;
        if (!expiresAt) return true;
        return new Date(expiresAt).getTime() > Date.now();
      },
    }),
    {
      name: 'vpn-pix-admin-auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        token: state.token,
        expiresAt: state.expiresAt,
        label: state.label,
        keyId: state.keyId,
      }),
    }
  )
);
