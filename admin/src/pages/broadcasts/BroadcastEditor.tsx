import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Ban,
  Eye,
  Image as ImageIcon,
  Loader2,
  Plus,
  Save,
  Send,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import { getErrorMessage } from '@/api/client';
import {
  cancelBroadcast,
  createBroadcast,
  getBroadcast,
  scheduleBroadcast,
  sendBroadcast,
  testBroadcast,
  updateBroadcast,
  uploadPhoto,
} from '@/api/endpoints/broadcasts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioItem } from '@/components/ui/radio-group';
import { TipTapEditor } from '@/components/editor/TipTapEditor';
import { cn } from '@/lib/utils';
import type {
  BroadcastButton,
  BroadcastStatus,
  BroadcastTarget,
} from '@/types';

const PHOTO_MAX_BYTES = 10 * 1024 * 1024;

const statusLabel: Record<BroadcastStatus, string> = {
  draft: 'черновик',
  scheduled: 'запланирована',
  sending: 'идёт отправка',
  done: 'завершена',
  cancelled: 'отменена',
};

function formatDate(value: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU');
  } catch {
    return value;
  }
}

export default function BroadcastEditor() {
  const { id: paramId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const isNew = paramId === 'new';
  const numericId = !isNew && paramId ? Number(paramId) : null;

  const query = useQuery({
    queryKey: ['broadcast', numericId],
    queryFn: () => getBroadcast(numericId!),
    enabled: numericId !== null,
  });

  const [draftId, setDraftId] = useState<number | null>(numericId);
  const [htmlText, setHtmlText] = useState('');
  const [target, setTarget] = useState<BroadcastTarget>('all');
  const [scheduleMode, setScheduleMode] = useState<'now' | 'scheduled'>('now');
  const [scheduledAt, setScheduledAt] = useState<string>('');
  const [buttons, setButtons] = useState<BroadcastButton[]>([]);
  const [buttonsPerRow, setButtonsPerRow] = useState(1);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoServerUrl, setPhotoServerUrl] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [status, setStatus] = useState<BroadcastStatus>('draft');

  // Hydrate from server when loaded
  useEffect(() => {
    if (query.data) {
      const b = query.data;
      setDraftId(b.id);
      setHtmlText(b.html_text ?? '');
      setTarget(b.target);
      setButtons(b.buttons ?? []);
      setButtonsPerRow(b.buttons_per_row ?? 1);
      setPhotoServerUrl(b.photo_url ?? null);
      setStatus(b.status);
      if (b.scheduled_at) {
        setScheduleMode('scheduled');
        setScheduledAt(toLocalInput(b.scheduled_at));
      } else {
        setScheduleMode('now');
        setScheduledAt('');
      }
    }
  }, [query.data]);

  useEffect(() => {
    if (!photoFile) {
      setPhotoPreview(null);
      return;
    }
    const url = URL.createObjectURL(photoFile);
    setPhotoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photoFile]);

  const readOnly = status === 'sending' || status === 'done' || status === 'cancelled';

  const createMut = useMutation({
    mutationFn: createBroadcast,
    onSuccess: async (b) => {
      setDraftId(b.id);
      toast.success('Черновик создан');
      // Если был файл — заливаем его
      if (photoFile) {
        await uploadAfterCreate(b.id);
      }
      void qc.invalidateQueries({ queryKey: ['broadcasts'] });
      navigate(`/broadcasts/${b.id}/edit`, { replace: true });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Parameters<typeof updateBroadcast>[1] }) =>
      updateBroadcast(id, payload),
    onSuccess: () => {
      toast.success('Сохранено');
      void qc.invalidateQueries({ queryKey: ['broadcast', draftId] });
      void qc.invalidateQueries({ queryKey: ['broadcasts'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const photoMut = useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => uploadPhoto(id, file),
    onSuccess: (b) => {
      toast.success('Фото загружено');
      setPhotoFile(null);
      setPhotoServerUrl(b.photo_url ?? null);
      void qc.invalidateQueries({ queryKey: ['broadcast', draftId] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const sendMut = useMutation({
    mutationFn: (id: number) => sendBroadcast(id),
    onSuccess: () => {
      toast.success('Запущена отправка');
      void qc.invalidateQueries({ queryKey: ['broadcast', draftId] });
      void qc.invalidateQueries({ queryKey: ['broadcasts'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const scheduleMut = useMutation({
    mutationFn: ({ id, scheduled_at }: { id: number; scheduled_at: string }) =>
      scheduleBroadcast(id, { scheduled_at }),
    onSuccess: () => {
      toast.success('Запланировано');
      void qc.invalidateQueries({ queryKey: ['broadcast', draftId] });
      void qc.invalidateQueries({ queryKey: ['broadcasts'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const cancelMut = useMutation({
    mutationFn: cancelBroadcast,
    onSuccess: () => {
      toast.success('Рассылка отменена');
      void qc.invalidateQueries({ queryKey: ['broadcast', draftId] });
      void qc.invalidateQueries({ queryKey: ['broadcasts'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const testMut = useMutation({
    mutationFn: ({ id, tg_id }: { id: number; tg_id: number }) =>
      testBroadcast(id, { tg_id }),
    onSuccess: () => {
      toast.success('Тестовое отправлено');
      setTestOpen(false);
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  async function uploadAfterCreate(id: number) {
    if (!photoFile) return;
    photoMut.mutate({ id, file: photoFile });
  }

  const buildPayload = () => ({
    html_text: htmlText,
    buttons: buttons.length ? buttons : null,
    buttons_per_row: buttonsPerRow,
    target,
  });

  const saveDraft = async () => {
    if (draftId == null) {
      createMut.mutate(buildPayload());
    } else {
      updateMut.mutate({ id: draftId, payload: buildPayload() });
      if (photoFile) photoMut.mutate({ id: draftId, file: photoFile });
    }
  };

  const ensureSavedThen = async (next: (id: number) => void) => {
    if (draftId == null) {
      const created = await createMut.mutateAsync(buildPayload());
      if (photoFile) await photoMut.mutateAsync({ id: created.id, file: photoFile });
      next(created.id);
    } else {
      await updateMut.mutateAsync({ id: draftId, payload: buildPayload() });
      if (photoFile) await photoMut.mutateAsync({ id: draftId, file: photoFile });
      next(draftId);
    }
  };

  const handleSendNow = () => {
    if (!htmlText.trim()) {
      toast.error('Текст не должен быть пустым');
      return;
    }
    if (!window.confirm('Запустить рассылку прямо сейчас?')) return;
    void ensureSavedThen((id) => sendMut.mutate(id));
  };

  const handleSchedule = () => {
    if (!scheduledAt) {
      toast.error('Укажите дату и время');
      return;
    }
    const iso = new Date(scheduledAt).toISOString();
    void ensureSavedThen((id) => scheduleMut.mutate({ id, scheduled_at: iso }));
  };

  const handlePrimaryAction = () => {
    if (scheduleMode === 'scheduled') {
      handleSchedule();
    } else {
      handleSendNow();
    }
  };

  const isPending =
    createMut.isPending ||
    updateMut.isPending ||
    photoMut.isPending ||
    sendMut.isPending ||
    scheduleMut.isPending;

  const data = query.data;

  if (numericId !== null && query.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate('/broadcasts')} type="button">
            <ArrowLeft className="h-4 w-4" />
            К списку
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {isNew ? 'Новая рассылка' : `Рассылка #${draftId}`}
            </h1>
            {data && (
              <p className="text-xs text-muted-foreground">
                Создана {formatDate(data.created_at)}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={readOnly ? 'destructive' : 'info'}>{statusLabel[status]}</Badge>
          {(status === 'scheduled' || status === 'sending') && draftId && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                if (window.confirm('Отменить рассылку?')) cancelMut.mutate(draftId);
              }}
              disabled={cancelMut.isPending}
              type="button"
            >
              <Ban className="h-4 w-4" />
              Отменить
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Сообщение</CardTitle>
            </CardHeader>
            <CardContent>
              <TipTapEditor
                value={htmlText}
                onChange={setHtmlText}
                disabled={readOnly}
                minHeight="220px"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Фото (опционально)</CardTitle>
            </CardHeader>
            <CardContent>
              <PhotoDropZone
                disabled={readOnly}
                file={photoFile}
                preview={photoPreview ?? photoServerUrl}
                onPick={(f) => {
                  if (f && f.size > PHOTO_MAX_BYTES) {
                    toast.error('Файл больше 10 МБ');
                    return;
                  }
                  setPhotoFile(f);
                  if (f && draftId != null) {
                    photoMut.mutate({ id: draftId, file: f });
                  }
                }}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Inline-кнопки</CardTitle>
            </CardHeader>
            <CardContent>
              <ButtonsEditor
                value={buttons}
                onChange={setButtons}
                perRow={buttonsPerRow}
                onPerRowChange={setButtonsPerRow}
                disabled={readOnly}
              />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Получатели</CardTitle>
            </CardHeader>
            <CardContent>
              <RadioGroup
                name="target"
                value={target}
                onValueChange={(v) => setTarget(v as BroadcastTarget)}
              >
                <RadioItem value="all" disabled={readOnly}>
                  Все пользователи бота
                </RadioItem>
                <RadioItem value="subscribers" disabled={readOnly}>
                  Только с активной подпиской
                </RadioItem>
              </RadioGroup>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Когда отправить</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <RadioGroup
                name="schedule"
                value={scheduleMode}
                onValueChange={(v) => setScheduleMode(v as typeof scheduleMode)}
              >
                <RadioItem value="now" disabled={readOnly}>
                  Сейчас
                </RadioItem>
                <RadioItem value="scheduled" disabled={readOnly}>
                  Запланировать
                </RadioItem>
              </RadioGroup>
              {scheduleMode === 'scheduled' && (
                <div className="space-y-1">
                  <Label htmlFor="when">Дата и время</Label>
                  <Input
                    id="when"
                    type="datetime-local"
                    value={scheduledAt}
                    onChange={(e) => setScheduledAt(e.target.value)}
                    disabled={readOnly}
                  />
                </div>
              )}
            </CardContent>
          </Card>

          {data && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Статистика</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                <div>
                  Получателей: <span className="font-mono">{data.recipients_total}</span>
                </div>
                <div>
                  Отправлено:{' '}
                  <span className="font-mono text-emerald-500">{data.sent}</span>
                </div>
                <div>
                  Ошибок: <span className="font-mono text-destructive">{data.failed}</span>
                </div>
                {data.started_at && (
                  <div className="text-xs text-muted-foreground">
                    Старт: {formatDate(data.started_at)}
                  </div>
                )}
                {data.finished_at && (
                  <div className="text-xs text-muted-foreground">
                    Финиш: {formatDate(data.finished_at)}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setPreviewOpen(true)}
            >
              <Eye className="h-4 w-4" />
              Превью
            </Button>
            <Button type="button" variant="outline" onClick={() => setTestOpen(true)}>
              <Send className="h-4 w-4" />
              Тест мне
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={saveDraft}
              disabled={readOnly || isPending}
            >
              <Save className="h-4 w-4" />
              Сохранить черновик
            </Button>
            <Button
              type="button"
              onClick={handlePrimaryAction}
              disabled={readOnly || isPending}
              className="ml-auto"
            >
              {isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {scheduleMode === 'scheduled' ? 'Запланировать' : 'Отправить'}
            </Button>
          </div>
        </div>
      </div>

      <PreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        html={htmlText}
        photoUrl={photoPreview ?? photoServerUrl ?? null}
        buttons={buttons}
        perRow={buttonsPerRow}
      />

      <TestDialog
        open={testOpen}
        onClose={() => setTestOpen(false)}
        isPending={testMut.isPending}
        onSubmit={(tg) =>
          ensureSavedThen((id) => testMut.mutate({ id, tg_id: tg }))
        }
      />
    </div>
  );
}

function toLocalInput(iso: string): string {
  try {
    const d = new Date(iso);
    const tzOffset = d.getTimezoneOffset() * 60_000;
    return new Date(d.getTime() - tzOffset).toISOString().slice(0, 16);
  } catch {
    return '';
  }
}

interface PhotoDropZoneProps {
  file: File | null;
  preview: string | null;
  disabled?: boolean;
  onPick: (file: File | null) => void;
}

function PhotoDropZone({ file, preview, disabled, onPick }: PhotoDropZoneProps) {
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const onFiles = (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    if (!/^image\/(png|jpeg)$/.test(f.type)) {
      toast.error('Только JPG/PNG');
      return;
    }
    onPick(f);
  };

  return (
    <div className="space-y-2">
      <div
        className={cn(
          'flex min-h-[140px] cursor-pointer items-center justify-center rounded-md border border-dashed border-input bg-background p-4 text-sm text-muted-foreground transition-colors',
          drag && 'border-primary bg-primary/5',
          disabled && 'cursor-not-allowed opacity-50'
        )}
        onDragOver={(e) => {
          if (disabled) return;
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          if (disabled) return;
          e.preventDefault();
          setDrag(false);
          onFiles(e.dataTransfer.files);
        }}
        onClick={() => !disabled && inputRef.current?.click()}
      >
        {preview ? (
          <div className="flex w-full flex-col items-center gap-2">
            <img src={preview} alt="" className="max-h-40 rounded-md object-contain" />
            {file && <span className="text-xs">{file.name}</span>}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <ImageIcon className="h-8 w-8" />
            <span>Перетащите фото сюда или нажмите, чтобы выбрать</span>
            <span className="text-xs">JPG/PNG, до 10 МБ</span>
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg"
          className="hidden"
          onChange={(e) => onFiles(e.target.files)}
        />
      </div>
      {preview && !disabled && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => onPick(null)}
        >
          <Trash2 className="h-4 w-4" />
          Убрать фото
        </Button>
      )}
    </div>
  );
}

interface ButtonsEditorProps {
  value: BroadcastButton[];
  onChange: (next: BroadcastButton[]) => void;
  perRow: number;
  onPerRowChange: (n: number) => void;
  disabled?: boolean;
}

function ButtonsEditor({
  value,
  onChange,
  perRow,
  onPerRowChange,
  disabled,
}: ButtonsEditorProps) {
  const update = (i: number, patch: Partial<BroadcastButton>) => {
    const next = value.slice();
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const next = value.slice();
    const tmp = next[i];
    next[i] = next[j];
    next[j] = tmp;
    onChange(next);
  };
  const add = () => {
    if (value.length >= 8) {
      toast.error('Максимум 8 кнопок');
      return;
    }
    onChange([...value, { text: '', url: '' }]);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {value.map((b, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input
              value={b.text}
              placeholder="Текст"
              onChange={(e) => update(i, { text: e.target.value })}
              disabled={disabled}
              className="flex-1"
            />
            <Input
              value={b.url}
              placeholder="https://"
              onChange={(e) => update(i, { url: e.target.value })}
              disabled={disabled}
              className="flex-[2]"
            />
            <Button
              type="button"
              size="icon"
              variant="ghost"
              disabled={disabled || i === 0}
              onClick={() => move(i, -1)}
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              disabled={disabled || i === value.length - 1}
              onClick={() => move(i, 1)}
            >
              <ArrowDown className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              disabled={disabled}
              onClick={() => remove(i)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        {value.length === 0 && (
          <p className="text-xs text-muted-foreground">Кнопок нет.</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={add}
        >
          <Plus className="h-4 w-4" />
          Добавить кнопку
        </Button>
        <div className="flex items-center gap-2">
          <Label htmlFor="per-row" className="text-xs">
            В строке
          </Label>
          <Input
            id="per-row"
            type="number"
            min={1}
            max={4}
            value={perRow}
            onChange={(e) => onPerRowChange(Math.max(1, Math.min(4, +e.target.value || 1)))}
            disabled={disabled}
            className="h-9 w-20"
          />
        </div>
      </div>
    </div>
  );
}

interface PreviewProps {
  open: boolean;
  onClose: () => void;
  html: string;
  photoUrl: string | null;
  buttons: BroadcastButton[];
  perRow: number;
}

function PreviewDialog({ open, onClose, html, photoUrl, buttons, perRow }: PreviewProps) {
  const rows = useMemo(() => {
    const out: BroadcastButton[][] = [];
    for (let i = 0; i < buttons.length; i += perRow) {
      out.push(buttons.slice(i, i + perRow));
    }
    return out;
  }, [buttons, perRow]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Превью</DialogTitle>
          <DialogDescription>
            Примерный вид сообщения в Telegram.
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg border border-border bg-card p-3 text-sm">
          {photoUrl && (
            <img src={photoUrl} alt="" className="mb-2 max-h-60 w-full rounded object-cover" />
          )}
          <div
            className="prose prose-sm max-w-none dark:prose-invert"
            dangerouslySetInnerHTML={{ __html: html || '<i>(пусто)</i>' }}
          />
          {rows.length > 0 && (
            <div className="mt-3 flex flex-col gap-2">
              {rows.map((row, ri) => (
                <div key={ri} className="grid gap-2" style={{ gridTemplateColumns: `repeat(${row.length}, minmax(0,1fr))` }}>
                  {row.map((b, bi) => (
                    <a
                      key={bi}
                      href={b.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-md border border-border bg-background px-2 py-1.5 text-center text-xs hover:bg-accent"
                    >
                      {b.text || '(без текста)'}
                    </a>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface TestDialogProps {
  open: boolean;
  onClose: () => void;
  isPending?: boolean;
  onSubmit: (tg_id: number) => void;
}

function TestDialog({ open, onClose, isPending, onSubmit }: TestDialogProps) {
  const [tg, setTg] = useState('');
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Тестовая отправка</DialogTitle>
          <DialogDescription>
            Введите tg_id получателя — будет отправлено только ему.
          </DialogDescription>
        </DialogHeader>
        <Input
          value={tg}
          onChange={(e) => setTg(e.target.value)}
          placeholder="123456789"
          inputMode="numeric"
        />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button
            disabled={!tg || isPending}
            onClick={() => {
              const n = Number(tg);
              if (!Number.isFinite(n)) return;
              onSubmit(n);
            }}
          >
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Отправить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
