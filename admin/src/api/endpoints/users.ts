import { api } from '@/api/client';
import type {
  BalanceAdjustRequest,
  BalanceSetRequest,
  BalanceTransaction,
  BanRequest,
  Page,
  User,
  UserListParams,
  UserPayment,
  UserReferrals,
  UserSubscriptionRow,
  UserTicket,
} from '@/types/api';

export const usersApi = {
  list: (params: UserListParams) =>
    api.get<Page<User>>('/admin/users', params as Record<string, unknown>),
  get: (id: number) => api.get<User>(`/admin/users/${id}`),
  payments: (id: number) => api.get<UserPayment[]>(`/admin/users/${id}/payments`),
  subscriptions: (id: number) =>
    api.get<UserSubscriptionRow[]>(`/admin/users/${id}/subscriptions`),
  tickets: (id: number) => api.get<UserTicket[]>(`/admin/users/${id}/tickets`),
  referrals: (id: number) => api.get<UserReferrals>(`/admin/users/${id}/referrals`),
  balanceHistory: (id: number) =>
    api.get<BalanceTransaction[]>(`/admin/users/${id}/balance-history`),
  ban: (id: number, payload: BanRequest) =>
    api.post<User, BanRequest>(`/admin/users/${id}/ban`, payload),
  unban: (id: number) => api.post<User>(`/admin/users/${id}/unban`),
  balanceAdjust: (id: number, payload: BalanceAdjustRequest) =>
    api.post<User, BalanceAdjustRequest>(`/admin/users/${id}/balance/adjust`, payload),
  balanceSet: (id: number, payload: BalanceSetRequest) =>
    api.post<User, BalanceSetRequest>(`/admin/users/${id}/balance/set`, payload),
};
