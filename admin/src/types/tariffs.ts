export interface TariffDuration {
  id: number;
  tariff_id: number;
  days: number;
  price_kopecks: number;
  is_hot: boolean;
  sort_order?: number;
}

export interface Tariff {
  id: number;
  code: string;
  name: string;
  description_html: string | null;
  devices: number;
  sort_order: number;
  is_active: boolean;
  is_free_trial?: boolean;
  free_trial_days?: number | null;
  // Conversion-pack 2026-05-13: marketing-only поле «обычный трафик GB/мес»
  // (NorthLine не enforce'ит). Отображается в карточке тарифа в боте.
  traffic_gb_per_month?: number | null;
  lte_gb_per_month?: number | null;
  durations: TariffDuration[];
  durations_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface TariffCreatePayload {
  code: string;
  name: string;
  description_html?: string | null;
  devices: number;
  sort_order?: number;
  is_active?: boolean;
  is_free_trial?: boolean;
  free_trial_days?: number | null;
  traffic_gb_per_month?: number | null;
  lte_gb_per_month?: number | null;
}

export interface TariffUpdatePayload {
  name?: string;
  description_html?: string | null;
  devices?: number;
  sort_order?: number;
  is_active?: boolean;
  is_free_trial?: boolean;
  free_trial_days?: number | null;
  traffic_gb_per_month?: number | null;
  lte_gb_per_month?: number | null;
}

export interface TariffDurationPayload {
  days: number;
  price_kopecks: number;
  is_hot?: boolean;
  sort_order?: number;
}
