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
}

export interface TariffUpdatePayload {
  name?: string;
  description_html?: string | null;
  devices?: number;
  sort_order?: number;
  is_active?: boolean;
}

export interface TariffDurationPayload {
  days: number;
  price_kopecks: number;
  is_hot?: boolean;
  sort_order?: number;
}
