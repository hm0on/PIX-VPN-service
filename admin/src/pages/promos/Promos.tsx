import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm, type SubmitHandler } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Dice5, Eye, Loader2, Pencil, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { getErrorMessage } from '@/api/client';
import {
  createPromo,
  getActivations,
  listPromos,
  updatePromo,
} from '@/api/endpoints/promos';
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
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ServerPaginatedTable, type Column } from '@/components/data-table/ServerPaginatedTable';
import type { Promo, PromoCreatePayload, PromoUpdatePayload, PromoType } from '@/types';

function generateCode(length = 8): string {
  // Crockford-ish base32 sans confusing chars
  const alphabet = 'ABCDEFGHJKMNPQRSTVWXYZ23456789';
  let s = '';
  const arr = new Uint32Array(length);
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(arr);
  }
  for (let i = 0; i < length; i++) {
    const r = (arr[i] ?? Math.floor(Math.random() * 1e9)) % alphabet.length;
    s += alphabet[r];
  }
  return s;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' });
  } catch {
    return value;
  }
}

/**
 * Convert a backend ISO timestamp (UTC) into the
 * "YYYY-MM-DDTHH:MM" string that <input type="datetime-local"> expects,
 * rendered in Moscow time. The admin entered the time in MSK; we round-trip it
 * back in MSK so the form shows what they typed (not what UTC stored it as).
 */
function formatForDateTimeLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  try {
    // 'sv-SE' gives ISO-ish "YYYY-MM-DD HH:MM:SS" output; we trim to minutes
    // and swap the space for the 'T' separator the input element wants.
    const msk = new Date(iso).toLocaleString('sv-SE', {
      timeZone: 'Europe/Moscow',
    });
    return msk.slice(0, 16).replace(' ', 'T');
  } catch {
    return '';
  }
}

const createSchema = z
  .object({
    code: z
      .string()
      .min(2, 'Минимум 2 символа')
      .max(64)
      .regex(/^[A-Za-z0-9_-]+$/, 'Только латиница, цифры, _ и -'),
    type: z.enum(['balance', 'discount_percent']),
    value: z.coerce.number().int().min(1, 'Минимум 1'),
    max_total_activations: z
      .union([z.coerce.number().int().min(1), z.literal('')])
      .transform((v) => (v === '' ? null : v))
      .nullable()
      .default(null),
    max_per_user: z.coerce.number().int().min(1).default(1),
    valid_from: z.string().optional().default(''),
    valid_until: z.string().optional().default(''),
    description: z.string().optional().default(''),
    is_active: z.boolean().default(true),
    // Conversion-pack 2026-05-13: optional binding to a specific user.
    // Empty string → null (legacy "anyone with the code" semantics).
    user_id: z
      .union([z.coerce.number().int().min(1), z.literal('')])
      .transform((v) => (v === '' ? null : v))
      .nullable()
      .default(null),
  })
  .refine((v) => v.type !== 'discount_percent' || v.value <= 100, {
    message: 'Скидка не может быть больше 100%',
    path: ['value'],
  });

type CreateFormValues = z.input<typeof createSchema>;
type CreateFormOutput = z.output<typeof createSchema>;

const editSchema = z.object({
  is_active: z.boolean().default(true),
  max_total_activations: z
    .union([z.coerce.number().int().min(1), z.literal('')])
    .transform((v) => (v === '' ? null : v))
    .nullable()
    .default(null),
  max_per_user: z.coerce.number().int().min(1).default(1),
  valid_until: z.string().optional().default(''),
});
type EditFormValues = z.input<typeof editSchema>;
type EditFormOutput = z.output<typeof editSchema>;

export default function Promos() {
  const qc = useQueryClient();
  const [activeOnly, setActiveOnly] = useState<'all' | 'active' | 'inactive'>('all');
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Promo | null>(null);
  const [activationsFor, setActivationsFor] = useState<Promo | null>(null);

  const promosQuery = useQuery({
    queryKey: [
      'promos',
      { activeOnly, search },
    ],
    queryFn: () =>
      listPromos({
        is_active: activeOnly === 'all' ? undefined : activeOnly === 'active',
        code: search || undefined,
      }),
  });

  const promos = promosQuery.data ?? [];

  const columns: Column<Promo>[] = useMemo(
    () => [
      { key: 'code', header: 'Код', cell: (p) => <span className="font-mono">{p.code}</span> },
      {
        key: 'type',
        header: 'Тип',
        cell: (p) =>
          p.type === 'balance' ? (
            <Badge variant="info">баланс</Badge>
          ) : (
            <Badge variant="secondary">скидка</Badge>
          ),
      },
      {
        key: 'value',
        header: 'Значение',
        cell: (p) =>
          p.type === 'balance' ? `${(p.value / 100).toFixed(2)} ₽` : `${p.value}%`,
      },
      {
        key: 'act',
        header: 'Активаций',
        cell: (p) => `${p.current_activations} / ${p.max_total_activations ?? '∞'}`,
      },
      { key: 'maxpu', header: 'На юзера', cell: (p) => p.max_per_user },
      { key: 'until', header: 'До', cell: (p) => formatDate(p.valid_until) },
      {
        key: 'is_active',
        header: 'Статус',
        cell: (p) =>
          p.is_active ? <Badge variant="success">активен</Badge> : <Badge variant="muted">нет</Badge>,
      },
      {
        key: 'actions',
        header: '',
        cell: (p) => (
          <div className="flex gap-1">
            <Button
              size="icon"
              variant="ghost"
              type="button"
              title="Редактировать"
              onClick={(e) => {
                e.stopPropagation();
                setEditing(p);
              }}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              type="button"
              title="Активации"
              onClick={(e) => {
                e.stopPropagation();
                setActivationsFor(p);
              }}
            >
              <Eye className="h-4 w-4" />
            </Button>
          </div>
        ),
        className: 'w-24 text-right',
      },
    ],
    []
  );

  const createMut = useMutation({
    mutationFn: (payload: PromoCreatePayload) => createPromo(payload),
    onSuccess: () => {
      toast.success('Промокод создан');
      setCreateOpen(false);
      void qc.invalidateQueries({ queryKey: ['promos'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Промокоды</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Промо для пополнения баланса или скидки на покупку.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          Создать
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Фильтры</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Label className="text-sm">Статус:</Label>
              <RadioGroup
                name="filter-active"
                value={activeOnly}
                onValueChange={(v) => setActiveOnly(v as typeof activeOnly)}
                className="flex flex-row gap-3"
              >
                <RadioItem value="all">Все</RadioItem>
                <RadioItem value="active">Активные</RadioItem>
                <RadioItem value="inactive">Неактивные</RadioItem>
              </RadioGroup>
            </div>
            <div className="flex items-center gap-2">
              <Label htmlFor="code-search" className="text-sm">
                Код:
              </Label>
              <Input
                id="code-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="WELCOME"
                className="h-9 w-48"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Список промокодов</CardTitle>
        </CardHeader>
        <CardContent>
          <ServerPaginatedTable
            columns={columns}
            rows={promos}
            isLoading={promosQuery.isLoading}
            rowKey={(p) => p.id}
            emptyMessage="Промокодов нет"
          />
        </CardContent>
      </Card>

      <CreatePromoDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        isPending={createMut.isPending}
        onSubmit={(payload) => createMut.mutate(payload)}
      />

      <EditPromoDialog
        promo={editing}
        onClose={() => setEditing(null)}
      />

      <ActivationsDialog promo={activationsFor} onClose={() => setActivationsFor(null)} />
    </div>
  );
}

interface CreateProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: PromoCreatePayload) => void;
  isPending?: boolean;
}

function CreatePromoDialog({ open, onClose, onSubmit, isPending }: CreateProps) {
  const form = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      code: '',
      type: 'balance',
      value: 100,
      max_total_activations: '',
      max_per_user: 1,
      valid_from: '',
      valid_until: '',
      description: '',
      is_active: true,
      user_id: '',
    },
  });

  const submit: SubmitHandler<CreateFormOutput> = (values) => {
    onSubmit({
      code: values.code,
      type: values.type as PromoType,
      value: values.value,
      max_total_activations: values.max_total_activations,
      max_per_user: values.max_per_user,
      valid_from: values.valid_from || null,
      valid_until: values.valid_until || null,
      description: values.description || null,
      is_active: values.is_active,
      user_id: values.user_id,
    });
  };

  const type = form.watch('type');
  const isActive = form.watch('is_active');

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Создать промокод</DialogTitle>
          <DialogDescription>
            Тип, значение и код после создания изменить нельзя — только активность, лимиты и срок.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={form.handleSubmit(submit as SubmitHandler<CreateFormValues>)}
          className="space-y-4"
        >
          <div className="space-y-1">
            <Label htmlFor="code">Код</Label>
            <div className="flex gap-2">
              <Input id="code" {...form.register('code')} placeholder="WELCOME2025" />
              <Button
                type="button"
                variant="outline"
                onClick={() => form.setValue('code', generateCode(8))}
              >
                <Dice5 className="h-4 w-4" />
                Сгенерировать
              </Button>
            </div>
            {form.formState.errors.code && (
              <p className="text-xs text-destructive">{form.formState.errors.code.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Тип</Label>
            <RadioGroup
              name="promo-type"
              value={type}
              onValueChange={(v) => form.setValue('type', v as PromoType)}
              className="flex flex-row gap-4"
            >
              <RadioItem value="balance">Баланс (₽)</RadioItem>
              <RadioItem value="discount_percent">Скидка (%)</RadioItem>
            </RadioGroup>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="value">
                Значение ({type === 'balance' ? 'копейки' : '%'})
              </Label>
              <Input id="value" type="number" min={1} {...form.register('value')} />
              {form.formState.errors.value && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.value.message}
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="max_total_activations">Лимит всего</Label>
              <Input
                id="max_total_activations"
                type="number"
                min={1}
                placeholder="без лимита"
                {...form.register('max_total_activations')}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="max_per_user">На юзера</Label>
              <Input
                id="max_per_user"
                type="number"
                min={1}
                {...form.register('max_per_user')}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="valid_from">Действует с</Label>
              <Input
                id="valid_from"
                type="datetime-local"
                {...form.register('valid_from')}
              />
              <p className="text-xs text-muted-foreground">МСК (Europe/Moscow)</p>
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="valid_until">Действует до</Label>
              <Input
                id="valid_until"
                type="datetime-local"
                {...form.register('valid_until')}
              />
              <p className="text-xs text-muted-foreground">МСК (Europe/Moscow)</p>
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="user_id">Привязать к юзеру</Label>
              <Input
                id="user_id"
                type="number"
                min={1}
                placeholder="внутренний users.id (необязательно)"
                {...form.register('user_id')}
              />
              <p className="text-xs text-muted-foreground">
                Если указан — промокод сработает только у этого юзера.
                Поле принимает <code>users.id</code> из админки, не Telegram tg_id.
              </p>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="description">Описание</Label>
            <Textarea id="description" rows={3} {...form.register('description')} />
          </div>

          <div className="flex items-center gap-3">
            <Switch
              checked={isActive}
              onCheckedChange={(v) => form.setValue('is_active', v)}
            />
            <Label className="cursor-pointer">Активен</Label>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface EditProps {
  promo: Promo | null;
  onClose: () => void;
}

function EditPromoDialog({ promo, onClose }: EditProps) {
  const qc = useQueryClient();
  const form = useForm<EditFormValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      is_active: promo?.is_active ?? true,
      max_total_activations: promo?.max_total_activations ?? '',
      max_per_user: promo?.max_per_user ?? 1,
      valid_until: formatForDateTimeLocal(promo?.valid_until),
    },
    values: promo
      ? {
          is_active: promo.is_active,
          max_total_activations: promo.max_total_activations ?? '',
          max_per_user: promo.max_per_user,
          valid_until: formatForDateTimeLocal(promo.valid_until),
        }
      : undefined,
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: PromoUpdatePayload }) =>
      updatePromo(id, payload),
    onSuccess: () => {
      toast.success('Сохранено');
      void qc.invalidateQueries({ queryKey: ['promos'] });
      onClose();
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  if (!promo) return null;

  const submit: SubmitHandler<EditFormOutput> = (values) => {
    updateMut.mutate({
      id: promo.id,
      payload: {
        is_active: values.is_active,
        max_total_activations: values.max_total_activations,
        max_per_user: values.max_per_user,
        valid_until: values.valid_until || null,
      },
    });
  };

  return (
    <Dialog open={!!promo} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Редактировать «{promo.code}»</DialogTitle>
          <DialogDescription>
            Можно изменить только статус, лимиты и срок действия.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={form.handleSubmit(submit as SubmitHandler<EditFormValues>)}
          className="space-y-3"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Тип</Label>
              <Input value={promo.type} disabled />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Значение</Label>
              <Input value={String(promo.value)} disabled />
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="max_total_activations">Лимит всего</Label>
            <Input
              id="max_total_activations"
              type="number"
              min={1}
              placeholder="без лимита"
              {...form.register('max_total_activations')}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="max_per_user">На юзера</Label>
            <Input
              id="max_per_user"
              type="number"
              min={1}
              {...form.register('max_per_user')}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="valid_until">Действует до</Label>
            <Input
              id="valid_until"
              type="datetime-local"
              {...form.register('valid_until')}
            />
            <p className="text-xs text-muted-foreground">МСК (Europe/Moscow)</p>
          </div>

          <div className="flex items-center gap-3">
            <Switch
              checked={form.watch('is_active')}
              onCheckedChange={(v) => form.setValue('is_active', v)}
            />
            <Label className="cursor-pointer">Активен</Label>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={updateMut.isPending}>
              {updateMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Сохранить
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface ActivationsProps {
  promo: Promo | null;
  onClose: () => void;
}

function ActivationsDialog({ promo, onClose }: ActivationsProps) {
  const query = useQuery({
    queryKey: ['promo-activations', promo?.id],
    queryFn: () => getActivations(promo!.id),
    enabled: !!promo,
  });

  return (
    <Dialog open={!!promo} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Активации «{promo?.code}»</DialogTitle>
          <DialogDescription>Список применений промокода.</DialogDescription>
        </DialogHeader>

        {query.isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : query.isError ? (
          <p className="text-sm text-destructive">{getErrorMessage(query.error)}</p>
        ) : (
          <div className="max-h-[60vh] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Юзер</TableHead>
                  <TableHead>Платёж</TableHead>
                  <TableHead>Сумма</TableHead>
                  <TableHead>Когда</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data ?? []).map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="text-xs">
                      {a.user_username
                        ? `@${a.user_username}`
                        : a.user_tg_id
                          ? `tg://${a.user_tg_id}`
                          : a.user_id}
                    </TableCell>
                    <TableCell className="text-xs">{a.payment_id ?? '—'}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {(a.applied_amount / 100).toFixed(2)} ₽
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(a.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
                {(query.data ?? []).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="h-16 text-center text-muted-foreground">
                      Активаций нет
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
