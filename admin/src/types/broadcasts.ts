export type BroadcastStatus = 'draft' | 'scheduled' | 'sending' | 'done' | 'cancelled';
export type BroadcastTarget = 'all' | 'subscribers';

export interface BroadcastButton {
  text: string;
  url: string;
}

export interface Broadcast {
  id: number;
  html_text: string;
  photo_file_id: string | null;
  photo_path: string | null;
  photo_url?: string | null;
  buttons: BroadcastButton[] | null;
  buttons_per_row?: number;
  target: BroadcastTarget;
  scheduled_at: string | null;
  status: BroadcastStatus;
  recipients_total: number;
  sent: number;
  failed: number;
  created_at: string;
  created_by_admin_key_label: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface BroadcastCreatePayload {
  html_text: string;
  buttons?: BroadcastButton[] | null;
  buttons_per_row?: number;
  target: BroadcastTarget;
}

export interface BroadcastUpdatePayload {
  html_text?: string;
  buttons?: BroadcastButton[] | null;
  buttons_per_row?: number;
  target?: BroadcastTarget;
  scheduled_at?: string | null;
}

export interface BroadcastSchedulePayload {
  scheduled_at: string;
}

export interface BroadcastTestPayload {
  tg_id: number;
}

export interface BroadcastRecipient {
  id: number;
  broadcast_id: number;
  user_id: number;
  status: 'pending' | 'sent' | 'failed';
  error: string | null;
  sent_at: string | null;
}
