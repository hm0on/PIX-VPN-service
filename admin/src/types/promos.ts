export type PromoType = 'balance' | 'discount_percent';

export interface Promo {
  id: number;
  code: string;
  type: PromoType;
  value: number; // kopecks for balance, percent for discount
  max_total_activations: number | null;
  max_per_user: number;
  current_activations: number;
  valid_from: string | null;
  valid_until: string | null;
  description: string | null;
  is_active: boolean;
  // Conversion-pack 2026-05-13: personal promo — non-null means the code
  // works only for this specific internal users.id (backend rejects with
  // ``not_for_this_user`` otherwise).
  user_id?: number | null;
  created_at?: string;
}

export interface PromoCreatePayload {
  code: string;
  type: PromoType;
  value: number;
  max_total_activations?: number | null;
  max_per_user?: number;
  valid_from?: string | null;
  valid_until?: string | null;
  description?: string | null;
  is_active?: boolean;
  user_id?: number | null;
}

export interface PromoUpdatePayload {
  is_active?: boolean;
  max_total_activations?: number | null;
  max_per_user?: number;
  valid_until?: string | null;
}

export interface PromoActivation {
  id: number;
  promo_id: number;
  user_id: number;
  user_tg_id?: number;
  user_username?: string | null;
  payment_id: number | null;
  applied_amount: number;
  created_at: string;
}
