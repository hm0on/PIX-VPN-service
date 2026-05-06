export type MediaKind = 'photo' | 'video' | 'animation';
export type TextKind = 'message' | 'button';

export interface BotText {
  key: string;
  description: string | null;
  value_html: string;
  media_file_id: string | null;
  media_kind: MediaKind | null;
  // Stage 6: 'message' rows are rich-text bodies edited in TipTap; 'button'
  // rows are plain inline-keyboard labels with an optional premium-emoji
  // icon id (icon_custom_emoji_id). The discriminator is set by backend
  // seeding and is not editable from the UI.
  kind: TextKind;
  icon_custom_emoji_id: string | null;
  // Optional outbound URL for kind='button' rows. When set, the bot renders
  // the button as a URL button instead of a callback button. Ignored for
  // kind='message' rows.
  url: string | null;
  updated_at: string | null;
}

export interface BotTextUpdatePayload {
  value_html?: string;
  description?: string | null;
  media_file_id?: string | null;
  media_kind?: MediaKind | null;
  icon_custom_emoji_id?: string | null;
  url?: string | null;
}
