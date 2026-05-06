import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Eye, Loader2, Save, Search, X } from 'lucide-react';
import { toast } from 'sonner';

import { getErrorMessage } from '@/api/client';
import { listTexts, updateText } from '@/api/endpoints/texts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { TipTapEditor } from '@/components/editor/TipTapEditor';
import { cn } from '@/lib/utils';
import type { MediaKind, TextKind } from '@/types';

const MEDIA_KINDS: MediaKind[] = ['photo', 'video', 'animation'];

// Filter chip values. 'all' is the default — admins land here looking for
// a key by name without caring whether it's a message or button. The two
// type-specific options are useful when bulk-renaming buttons (a Phase-1
// activity) or auditing message copy.
type KindFilter = 'all' | TextKind;

function formatDate(value: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU');
  } catch {
    return value;
  }
}

export default function BotTexts() {
  const qc = useQueryClient();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [kindFilter, setKindFilter] = useState<KindFilter>('all');
  const [draft, setDraft] = useState<string>('');
  const [iconEmojiId, setIconEmojiId] = useState<string>('');
  const [urlDraft, setUrlDraft] = useState<string>('');
  const [mediaFileId, setMediaFileId] = useState<string>('');
  const [mediaKind, setMediaKind] = useState<MediaKind>('photo');
  const [previewOpen, setPreviewOpen] = useState(false);

  const query = useQuery({ queryKey: ['bot-texts'], queryFn: listTexts });
  const texts = useMemo(() => query.data ?? [], [query.data]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return texts.filter((t) => {
      if (kindFilter !== 'all' && t.kind !== kindFilter) return false;
      if (!q) return true;
      return (
        t.key.toLowerCase().includes(q) ||
        (t.description ?? '').toLowerCase().includes(q) ||
        // Search the label too — for buttons this is the visible text, so
        // typing "Каталог" should surface btn.main_menu.catalog.
        (t.value_html ?? '').toLowerCase().includes(q)
      );
    });
  }, [texts, search, kindFilter]);

  const selected = useMemo(
    () => texts.find((t) => t.key === selectedKey) ?? null,
    [texts, selectedKey]
  );

  useEffect(() => {
    setDraft(selected?.value_html ?? '');
    setIconEmojiId(selected?.icon_custom_emoji_id ?? '');
    setUrlDraft(selected?.url ?? '');
    setMediaFileId(selected?.media_file_id ?? '');
    setMediaKind((selected?.media_kind as MediaKind | null) ?? 'photo');
  }, [
    selected?.key,
    selected?.value_html,
    selected?.icon_custom_emoji_id,
    selected?.url,
    selected?.media_file_id,
    selected?.media_kind,
  ]);

  const updateMut = useMutation({
    mutationFn: ({
      key,
      value_html,
      icon_custom_emoji_id,
      url,
      media_file_id,
      media_kind,
    }: {
      key: string;
      value_html: string;
      icon_custom_emoji_id: string | null;
      url: string | null;
      media_file_id: string | null;
      media_kind: MediaKind | null;
    }) =>
      updateText(key, {
        value_html,
        icon_custom_emoji_id,
        url,
        media_file_id,
        media_kind,
      }),
    onSuccess: () => {
      toast.success('Текст обновлён');
      void qc.invalidateQueries({ queryKey: ['bot-texts'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const handleSave = () => {
    if (!selected) return;
    const isButton = selected.kind === 'button';
    // For button rows we never send media_* — buttons can't carry an
    // attachment. The icon-id and URL pair always travels (null clears it).
    const trimmedFileId = mediaFileId.trim();
    const fileIdPayload = !isButton && trimmedFileId.length > 0 ? trimmedFileId : null;
    const kindPayload = !isButton && trimmedFileId.length > 0 ? mediaKind : null;
    const trimmedIcon = iconEmojiId.trim();
    const iconPayload = isButton && trimmedIcon.length > 0 ? trimmedIcon : null;
    const trimmedUrl = urlDraft.trim();
    const urlPayload = isButton && trimmedUrl.length > 0 ? trimmedUrl : null;

    updateMut.mutate({
      key: selected.key,
      value_html: draft,
      icon_custom_emoji_id: iconPayload,
      url: urlPayload,
      media_file_id: fileIdPayload,
      media_kind: kindPayload,
    });
  };

  const isButton = selected?.kind === 'button';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Тексты бота</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Сообщения, которые бот шлёт юзерам, и подписи кнопок в инлайн-клавиатурах.
          Сообщения редактируются как HTML, кнопки — как обычная строка с опциональным
          премиум-эмодзи слева. Изменения применяются мгновенно.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Ключи</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <KindFilterTabs value={kindFilter} onChange={setKindFilter} />
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск по ключу, описанию или тексту"
                className="pl-8"
              />
            </div>
            {query.isLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : (
              <ul className="max-h-[60vh] overflow-auto">
                {filtered.map((t) => (
                  <li key={t.key}>
                    <button
                      type="button"
                      onClick={() => setSelectedKey(t.key)}
                      className={cn(
                        'block w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent',
                        selectedKey === t.key && 'bg-accent'
                      )}
                    >
                      <div className="flex items-center gap-1.5 font-mono text-xs">
                        {t.key}
                        <KindBadge kind={t.kind} />
                        {t.media_file_id ? (
                          <span
                            title={`media: ${t.media_kind ?? 'photo'}`}
                            className="rounded bg-primary/15 px-1 text-[9px] uppercase tracking-wider text-primary"
                          >
                            {t.media_kind ?? 'media'}
                          </span>
                        ) : null}
                        {t.icon_custom_emoji_id ? (
                          <span
                            title={`icon emoji id: ${t.icon_custom_emoji_id}`}
                            className="rounded bg-amber-500/15 px-1 text-[9px] uppercase tracking-wider text-amber-600 dark:text-amber-400"
                          >
                            emoji
                          </span>
                        ) : null}
                        {t.url ? (
                          <span
                            title={`url: ${t.url}`}
                            className="rounded bg-sky-500/15 px-1 text-[9px] uppercase tracking-wider text-sky-600 dark:text-sky-400"
                          >
                            url
                          </span>
                        ) : null}
                      </div>
                      {t.description && (
                        <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                          {t.description}
                        </div>
                      )}
                      <div className="mt-0.5 text-[10px] text-muted-foreground">
                        {formatDate(t.updated_at)}
                      </div>
                    </button>
                  </li>
                ))}
                {filtered.length === 0 && (
                  <li className="py-6 text-center text-xs text-muted-foreground">
                    Ничего не найдено
                  </li>
                )}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between space-y-0">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-base">
                {selected ? selected.key : 'Выберите ключ'}
                {selected ? <KindBadge kind={selected.kind} /> : null}
              </CardTitle>
              {selected?.description && (
                <p className="text-xs text-muted-foreground">{selected.description}</p>
              )}
            </div>
            {selected && (
              <div className="flex gap-2">
                {!isButton && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setPreviewOpen(true)}
                  >
                    <Eye className="h-4 w-4" />
                    Превью
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  onClick={handleSave}
                  disabled={updateMut.isPending}
                >
                  {updateMut.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  Сохранить
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {!selected ? (
              <p className="text-sm text-muted-foreground">
                Выберите ключ слева, чтобы редактировать.
              </p>
            ) : isButton ? (
              <ButtonEditor
                label={draft}
                onLabelChange={setDraft}
                iconEmojiId={iconEmojiId}
                onIconEmojiIdChange={setIconEmojiId}
                url={urlDraft}
                onUrlChange={setUrlDraft}
              />
            ) : (
              <>
                <TipTapEditor value={draft} onChange={setDraft} minHeight="300px" />
                <MediaAttachment
                  fileId={mediaFileId}
                  kind={mediaKind}
                  onFileIdChange={setMediaFileId}
                  onKindChange={setMediaKind}
                />
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <PreviewTextDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        html={draft}
        title={selected?.key ?? null}
      />
    </div>
  );
}

interface KindBadgeProps {
  kind: TextKind;
}

function KindBadge({ kind }: KindBadgeProps) {
  if (kind === 'button') {
    return (
      <span className="rounded bg-emerald-500/15 px-1 text-[9px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
        button
      </span>
    );
  }
  return (
    <span className="rounded bg-blue-500/15 px-1 text-[9px] uppercase tracking-wider text-blue-600 dark:text-blue-400">
      msg
    </span>
  );
}

interface KindFilterProps {
  value: KindFilter;
  onChange: (v: KindFilter) => void;
}

function KindFilterTabs({ value, onChange }: KindFilterProps) {
  const opts: Array<{ id: KindFilter; label: string }> = [
    { id: 'all', label: 'Все' },
    { id: 'message', label: 'Сообщения' },
    { id: 'button', label: 'Кнопки' },
  ];
  return (
    <div className="flex gap-1 rounded-md border border-border bg-muted/40 p-1">
      {opts.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          className={cn(
            'flex-1 rounded px-2 py-1 text-xs transition-colors hover:bg-accent',
            value === o.id && 'bg-background font-medium shadow-sm'
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

interface ButtonEditorProps {
  label: string;
  onLabelChange: (v: string) => void;
  iconEmojiId: string;
  onIconEmojiIdChange: (v: string) => void;
  url: string;
  onUrlChange: (v: string) => void;
}

function ButtonEditor({
  label,
  onLabelChange,
  iconEmojiId,
  onIconEmojiIdChange,
  url,
  onUrlChange,
}: ButtonEditorProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="text-sm font-medium">Текст кнопки</label>
        <Input
          value={label}
          onChange={(e) => onLabelChange(e.target.value)}
          placeholder="Например: Каталог"
          maxLength={64}
        />
        <p className="text-xs text-muted-foreground">
          Telegram отображает кнопку как обычный текст без HTML, эмодзи и форматирования.
          Стандартные эмодзи (🚀, ✅) работают, кастомные премиум-эмодзи нужно прикрепить
          через поле ниже.
        </p>
      </div>

      <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium">URL (опционально)</h3>
            <p className="text-xs text-muted-foreground">
              Если задано — кнопка станет ссылкой и откроет этот URL вместо
              callback-действия. Например, для кнопок раздела «О проекте»
              (<code>btn.about.privacy</code>, <code>btn.about.terms</code>,
              <code> btn.about.channel</code>). Допустимы схемы{' '}
              <code>https://</code>, <code>http://</code>, <code>tg://</code>.
            </p>
          </div>
          {url.trim().length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onUrlChange('')}
              title="Очистить URL"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
        <Input
          value={url}
          onChange={(e) => onUrlChange(e.target.value)}
          placeholder="https://example.com или tg://resolve?domain=..."
          className="font-mono text-xs"
          maxLength={512}
        />
      </div>

      <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium">Премиум-эмодзи (опционально)</h3>
            <p className="text-xs text-muted-foreground">
              ID кастомного эмодзи Telegram, который будет показан слева от текста кнопки.
              Узнать ID: переслать сообщение с эмодзи в{' '}
              <a
                href="https://t.me/TestEmojiBot"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline"
              >
                @TestEmojiBot
              </a>{' '}
              или через Bot API <code>getCustomEmojiStickers</code>.
            </p>
          </div>
          {iconEmojiId.trim().length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onIconEmojiIdChange('')}
              title="Очистить эмодзи"
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
        <Input
          value={iconEmojiId}
          onChange={(e) => onIconEmojiIdChange(e.target.value)}
          placeholder="Document ID кастомного эмодзи (напр. 5368324170671202286)"
          className="font-mono text-xs"
          maxLength={64}
        />
      </div>
    </div>
  );
}

interface MediaAttachmentProps {
  fileId: string;
  kind: MediaKind;
  onFileIdChange: (v: string) => void;
  onKindChange: (k: MediaKind) => void;
}

function MediaAttachment({
  fileId,
  kind,
  onFileIdChange,
  onKindChange,
}: MediaAttachmentProps) {
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Медиа-вложение</h3>
          <p className="text-xs text-muted-foreground">
            Опционально. Если задано — бот отправит текст как подпись к фото / видео / GIF.
            <br />
            Получить <code>file_id</code>: отправьте медиа в группу поддержки → реплай{' '}
            <code>/getfileid</code>.
          </p>
        </div>
        {fileId.trim().length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onFileIdChange('')}
            title="Очистить вложение"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-[140px_1fr]">
        <select
          value={kind}
          onChange={(e) => onKindChange(e.target.value as MediaKind)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          {MEDIA_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <Input
          value={fileId}
          onChange={(e) => onFileIdChange(e.target.value)}
          placeholder="file_id (вставьте сюда)"
          className="font-mono text-xs"
        />
      </div>
    </div>
  );
}

interface PreviewProps {
  open: boolean;
  onClose: () => void;
  html: string;
  title: string | null;
}

function PreviewTextDialog({ open, onClose, html, title }: PreviewProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title ?? 'Превью'}</DialogTitle>
        </DialogHeader>
        <div
          className="prose prose-sm max-w-none rounded-md border border-border bg-card p-3 dark:prose-invert"
          dangerouslySetInnerHTML={{ __html: html || '<i>(пусто)</i>' }}
        />
        <DialogFooter>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
