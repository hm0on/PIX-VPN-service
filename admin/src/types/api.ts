/**
 * Shared API types for the admin panel.
 *
 * These mirror the documented Stage 5 backend contract. When the backend
 * agent finalises endpoints, adjust here.
 */

/* ---------- Pagination ---------- */

export interface PageMeta {
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface Page<T> {
  items: T[];
  meta: PageMeta;
}

export interface ListParams {
  page?: number;
  per_page?: number;
  sort?: string; // `field:asc` | `field:desc`
  q?: string;
}

/* ---------- Dashboard ---------- */

export interface DashboardKPI {
  users_total: number;
  users_delta_24h: number;
  active_subscriptions: number;
  revenue_month_kop: number;
  revenue_today_kop: number;
}

export type Period = '30d' | '90d' | '365d';

export interface RevenuePoint {
  date: string; // ISO date (YYYY-MM-DD)
  amount_kop: number;
}

export interface UsersPoint {
  date: string;
  count: number;
}

export interface RecentPayment {
  id: number;
  user_id: number;
  user_username: string | null;
  user_tg_id: number;
  amount_kop: number;
  provider: string;
  status: string;
  subscription_id: number | null;
  created_at: string;
}

export interface RecentUser {
  id: number;
  tg_id: number;
  username: string | null;
  first_name: string | null;
  created_at: string;
}

/* ---------- Users ---------- */

export interface User {
  id: number;
  tg_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  balance_kop: number;
  active_subscriptions_count: number;
  is_banned: boolean;
  ban_reason: string | null;
  banned_at: string | null;
  referrer_id: number | null;
  created_at: string;
}

export interface UserListParams extends ListParams {
  banned?: boolean;
  with_subscription?: boolean;
  balance_gt?: number;
}

export interface UserPayment {
  id: number;
  amount_kop: number;
  provider: string;
  status: string;
  subscription_id: number | null;
  created_at: string;
  paid_at: string | null;
}

export interface UserSubscriptionRow {
  id: number;
  tariff_code: string | null;
  tariff_name: string | null;
  devices: number;
  status: string;
  expires_at: string | null;
  created_at: string;
  is_free_trial: boolean;
}

export interface UserTicket {
  id: number;
  code: string;
  kind: string;
  status: string;
  topic_thread_id: number | null;
  group_link: string | null;
  created_at: string;
  closed_at: string | null;
}

export interface UserReferral {
  id: number;
  tg_id: number;
  username: string | null;
  created_at: string;
  has_paid: boolean;
  bonus_kop: number;
}

export interface UserReferrals {
  referrer: {
    id: number;
    tg_id: number;
    username: string | null;
  } | null;
  invited: UserReferral[];
}

export interface BalanceTransaction {
  id: number;
  amount_kop: number; // signed
  reason: string;
  comment: string | null;
  admin_label: string | null;
  created_at: string;
}

export interface BanRequest {
  reason: string;
}

export interface BalanceAdjustRequest {
  amount_kop: number; // signed
  reason: string;
}

/* ---------- Subscriptions ---------- */

export interface Subscription {
  id: number;
  user_id: number;
  user_username: string | null;
  user_tg_id: number;
  tariff_code: string | null;
  tariff_name: string | null;
  devices: number;
  days: number | null;
  key_url: string | null;
  status: string; // active, expired, deactivated, ...
  is_free_trial: boolean;
  expires_at: string | null;
  created_at: string;
  deactivated_at: string | null;
  deactivation_reason: string | null;
}

export interface SubscriptionListParams extends ListParams {
  status?: string;
  tariff?: string;
  is_free_trial?: boolean;
  expires_from?: string;
  expires_to?: string;
}

export interface SubscriptionDevice {
  id: string;
  name?: string | null;
  last_seen_at?: string | null;
  ip?: string | null;
  user_agent?: string | null;
}

export interface SubscriptionInfo {
  traffic_bytes: number | null;
  lte_traffic_bytes: number | null;
  devices: SubscriptionDevice[];
  expires_at: string | null;
  raw?: Record<string, unknown>;
}

export interface DeactivateRequest {
  reason: string;
}
