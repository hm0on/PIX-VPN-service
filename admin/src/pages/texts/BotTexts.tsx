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
import type { MediaKind } from '@/types';

const MEDIA_KINDS: MediaKind[] = ['photo', 'video', 'animation'];

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
  const [draft, setDraft] = useState<string>('');
  const [mediaFileId, setMediaFileId] = useState<string>('');
  const [mediaKind, setMediaKind] = useState<MediaKind>('photo');
  const [previewOpen, setPreviewOpen] = useState(false);

  const query = useQuery({ queryKey: ['bot-texts'], queryFn: listTexts });
  const texts = useMemo(() => query.data ?? [], [query.data]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return texts;
    return texts.filter(
      (t) =>
        t.key.toLowerCase().includes(q) ||
        (t.description ?? '').toLowerCase().includes(q)
    );
  }, [texts, search]);

  const selected = useMemo(
    () => texts.find((t) => t.key === selectedKey) ?? null,
    [texts, selectedKey]
  );

  useEffect(() => {
    setDraft(selected?.value_html ?? '');
    setMediaFileId(selected?.media_file_id ?? '');
    setMediaKind((selected?.media_kind as MediaKind | null) ?? 'photo');
  }, [selected?.key, selected?.value_html, selected?.media_file_id, selected?.media_kind]);

  const updateMut = useMutation({
    mutationFn: ({
      key,
      value_html,
      media_file_id,
      media_kind,
    }: {
      key: string;
      value_html: string;
      media_file_id: string | null;
      media_kind: MediaKind | null;
    }) =>
      updateText(key, {
        value_html,
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
    const trimmedFileId = mediaFileId.trim();
    // media_file_id and media_kind must travel as a pair (both filled or both null)
    const fileIdPayload = trimmedFileId.length > 0 ? trimmedFileId : null;
    const kindPayload = trimmedFileId.length > 0 ? mediaKind : null;
    updateMut.mutate({
      key: selected.key,
      value_html: draft,
      media_file_id: fileIdPayload,
      media_kind: kindPayload,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Тексты бота</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Сообщения, которые бот шлёт юзерам. Можно прикрепить картинку/видео/гифку
          — бот пришлёт её вместе с текстом. Изменения применяются мгновенно.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Ключи</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск по ключу или описанию"
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
                        {t.media_file_id ? (
                          <span
                            title={`media: ${t.media_kind ?? 'photo'}`}
                            className="rounded bg-primary/15 px-1 text-[9px] uppercase tracking-wider text-primary"
                          >
                            {t.media_kind ?? 'media'}
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
              <CardTitle className="text-base">
                {selected ? selected.key : 'Выберите ключ'}
              </CardTitle>
              {selected?.description && (
                <p className="text-xs text-muted-foreground">{selected.description}</p>
              )}
            </div>
            {selected && (
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setPreviewOpen(true)}
                >
                  <Eye className="h-4 w-4" />
                  Превью
                </Button>
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
            {selected ? (
              <>
                <TipTapEditor value={draft} onChange={setDraft} minHeight="300px" />
                <MediaAttachment
                  fileId={mediaFileId}
                  kind={mediaKind}
                  onFileIdChange={setMediaFileId}
                  onKindChange={setMediaKind}
                />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Выберите ключ слева, чтобы редактировать.
              </p>
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
