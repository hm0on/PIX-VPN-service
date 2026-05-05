export type MediaKind = 'photo' | 'video' | 'animation';

export interface BotText {
  key: string;
  description: string | null;
  value_html: string;
  media_file_id: string | null;
  media_kind: MediaKind | null;
  updated_at: string | null;
}

export interface BotTextUpdatePayload {
  value_html?: string;
  description?: string | null;
  media_file_id?: string | null;
  media_kind?: MediaKind | null;
}
