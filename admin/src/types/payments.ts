/**
 * Global payments admin DTOs.
 *
 * Mirrors backend.app.schemas.admin_panel.payments.
 */

export type PaymentStatus = 'pending' | 'paid' | 'failed' | 'expired' | 'refunded';
export type PaymentProvider =
  | 'platega_sbp'
  | 'platega_crypto'
  | 'cryptobot'
  | 'balance';
export type PaymentPurpose = 'subscription' | 'topup';

export interface AdminPaymentListItem {
  id: number;
  user_id: number;
  user_tg_id: number | null;
  user_username: string | null;
  subscription_id: number | null;
  purpose: string;
  provider: string;
  external_id: string | null;
  amount_kop: number;
  currency: string;
  status: string;
  created_at: string;
  paid_at: string | null;
}

export interface AdminPaymentsListParams {
  status?: string;
  provider?: string;
  purpose?: string;
  user_id?: number;
  created_from?: string;
  created_to?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface AdminPaymentsPage {
  items: AdminPaymentListItem[];
  total: number;
  page: number;
  page_size: number;
}
