import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm, type SubmitHandler } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, Plus, Trash2, Check, X, Pencil } from 'lucide-react';
import { toast } from 'sonner';

import { getErrorMessage } from '@/api/client';
import {
  addDuration,
  createTariff,
  listTariffs,
  removeDuration,
  removeTariff,
  updateDuration,
  updateTariff,
} from '@/api/endpoints/tariffs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TipTapEditor } from '@/components/editor/TipTapEditor';
import { ServerPaginatedTable, type Column } from '@/components/data-table/ServerPaginatedTable';
import type {
  Tariff,
  TariffCreatePayload,
  TariffDuration,
  TariffUpdatePayload,
} from '@/types';

const tariffSchema = z.object({
  code: z
    .string()
    .min(2, 'Минимум 2 символа')
    .max(64)
    .regex(/^[a-z0-9_-]+$/i, 'Только латиница, цифры, _ и -'),
  name: z.string().min(1, 'Обязательно'),
  description_html: z.string().optional().default(''),
  devices: z.coerce.number().int().min(1).max(20),
  sort_order: z.coerce.number().int().min(0).default(0),
  is_active: z.boolean().default(true),
  // Conversion-pack 2026-05-13: traffic (regular + LTE) — marketing fields.
  // Empty string → null, otherwise non-negative int.
  traffic_gb_per_month: z
    .union([z.coerce.number().int().min(0), z.literal('')])
    .transform((v) => (v === '' ? null : v))
    .nullable()
    .default(null),
  lte_gb_per_month: z
    .union([z.coerce.number().int().min(0), z.literal('')])
    .transform((v) => (v === '' ? null : v))
    .nullable()
    .default(null),
});

type TariffFormValues = z.infer<typeof tariffSchema>;

const NEW_ID = -1;

export default function Tariffs() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const tariffsQuery = useQuery({ queryKey: ['tariffs'], queryFn: listTariffs });
  const tariffs = useMemo(() => tariffsQuery.data ?? [], [tariffsQuery.data]);

  const selected = useMemo(
    () => tariffs.find((t) => t.id === selectedId) ?? null,
    [tariffs, selectedId]
  );
  const isCreating = selectedId === NEW_ID;

  const columns: Column<Tariff>[] = [
    { key: 'code', header: 'Код', cell: (t) => <span className="font-mono text-xs">{t.code}</span> },
    { key: 'name', header: 'Название', cell: (t) => t.name },
    { key: 'devices', header: 'Устр-в', cell: (t) => t.devices, className: 'w-20' },
    { key: 'sort', header: 'Порядок', cell: (t) => t.sort_order, className: 'w-20' },
    {
      key: 'active',
      header: 'Активен',
      cell: (t) =>
        t.is_active ? (
          <Badge variant="success">да</Badge>
        ) : (
          <Badge variant="muted">нет</Badge>
        ),
      className: 'w-24',
    },
    {
      key: 'durations',
      header: 'Цен',
      cell: (t) => t.durations?.length ?? t.durations_count ?? 0,
      className: 'w-16',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Тарифы</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Тарифы и матрица цен. Изменения применяются мгновенно.
          </p>
        </div>
        <Button onClick={() => setSelectedId(NEW_ID)}>
          <Plus className="h-4 w-4" />
          Создать тариф
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Список</CardTitle>
          </CardHeader>
          <CardContent>
            <ServerPaginatedTable
              columns={columns}
              rows={tariffs}
              isLoading={tariffsQuery.isLoading}
              rowKey={(t) => t.id}
              onRowClick={(t) => setSelectedId(t.id)}
              emptyMessage="Тарифов нет"
            />
            {tariffsQuery.isError && (
              <p className="mt-2 text-sm text-destructive">
                {getErrorMessage(tariffsQuery.error)}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">
              {isCreating ? 'Новый тариф' : selected ? `Редактирование: ${selected.code}` : 'Выберите тариф'}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isCreating || selected ? (
              <TariffEditor
                key={isCreating ? 'new' : selected!.id}
                tariff={isCreating ? null : selected}
                onCreated={(t) => {
                  setSelectedId(t.id);
                  void qc.invalidateQueries({ queryKey: ['tariffs'] });
                }}
                onDeleted={() => {
                  setSelectedId(null);
                  void qc.invalidateQueries({ queryKey: ['tariffs'] });
                }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                Кликните по строке слева, чтобы редактировать, или создайте новый.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

interface TariffEditorProps {
  tariff: Tariff | null;
  onCreated: (t: Tariff) => void;
  onDeleted: () => void;
}

function TariffEditor({ tariff, onCreated, onDeleted }: TariffEditorProps) {
  const qc = useQueryClient();
  const isNew = !tariff;

  const form = useForm<TariffFormValues>({
    resolver: zodResolver(tariffSchema),
    defaultValues: {
      code: tariff?.code ?? '',
      name: tariff?.name ?? '',
      description_html: tariff?.description_html ?? '',
      devices: tariff?.devices ?? 1,
      sort_order: tariff?.sort_order ?? 0,
      is_active: tariff?.is_active ?? true,
      // Schema after .transform() resolves to `number | null` so we
      // explicitly map the absent-value case to null instead of ''.
      traffic_gb_per_month: tariff?.traffic_gb_per_month ?? null,
      lte_gb_per_month: tariff?.lte_gb_per_month ?? null,
    },
  });

  useEffect(() => {
    form.reset({
      code: tariff?.code ?? '',
      name: tariff?.name ?? '',
      description_html: tariff?.description_html ?? '',
      devices: tariff?.devices ?? 1,
      sort_order: tariff?.sort_order ?? 0,
      is_active: tariff?.is_active ?? true,
      traffic_gb_per_month: tariff?.traffic_gb_per_month ?? null,
      lte_gb_per_month: tariff?.lte_gb_per_month ?? null,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tariff?.id]);

  const createMut = useMutation({
    mutationFn: (payload: TariffCreatePayload) => createTariff(payload),
    onSuccess: (t) => {
      toast.success('Тариф создан');
      onCreated(t);
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: TariffUpdatePayload }) =>
      updateTariff(id, payload),
    onSuccess: () => {
      toast.success('Сохранено');
      void qc.invalidateQueries({ queryKey: ['tariffs'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });
  const removeMut = useMutation({
    mutationFn: (id: number) => removeTariff(id),
    onSuccess: () => {
      toast.success('Тариф удалён');
      onDeleted();
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const onSubmit: SubmitHandler<TariffFormValues> = (values) => {
    if (isNew) {
      createMut.mutate({
        code: values.code,
        name: values.name,
        description_html: values.description_html || null,
        devices: values.devices,
        sort_order: values.sort_order,
        is_active: values.is_active,
        traffic_gb_per_month: values.traffic_gb_per_month,
        lte_gb_per_month: values.lte_gb_per_month,
      });
    } else {
      updateMut.mutate({
        id: tariff!.id,
        payload: {
          name: values.name,
          description_html: values.description_html || null,
          devices: values.devices,
          sort_order: values.sort_order,
          is_active: values.is_active,
          traffic_gb_per_month: values.traffic_gb_per_month,
          lte_gb_per_month: values.lte_gb_per_month,
        },
      });
    }
  };

  const isActive = form.watch('is_active');
  const desc = form.watch('description_html');

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="code">Код</Label>
          <Input
            id="code"
            {...form.register('code')}
            disabled={!isNew}
            placeholder="basic"
          />
          {form.formState.errors.code && (
            <p className="text-xs text-destructive">{form.formState.errors.code.message}</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="name">Название</Label>
          <Input id="name" {...form.register('name')} placeholder="Базовый" />
          {form.formState.errors.name && (
            <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="devices">Устройств</Label>
          <Input
            id="devices"
            type="number"
            min={1}
            max={20}
            {...form.register('devices')}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="sort_order">Порядок</Label>
          <Input id="sort_order" type="number" min={0} {...form.register('sort_order')} />
        </div>
        {/* Conversion-pack 2026-05-13: маркетинговые поля трафика.
            NorthLine не enforce'ит обычный трафик (cap живёт только в UI);
            LTE — отдельный add-on, который NorthLine выдаёт фактически.  */}
        <div className="space-y-1">
          <Label htmlFor="traffic_gb_per_month">Трафик, GB/мес</Label>
          <Input
            id="traffic_gb_per_month"
            type="number"
            min={0}
            placeholder="пусто = безлимит"
            {...form.register('traffic_gb_per_month')}
          />
          <p className="text-xs text-muted-foreground">
            Маркетинговое поле, не enforce'ится провайдером.
          </p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="lte_gb_per_month">LTE-трафик, GB/мес</Label>
          <Input
            id="lte_gb_per_month"
            type="number"
            min={0}
            placeholder="по умолчанию 35"
            {...form.register('lte_gb_per_month')}
          />
          <p className="text-xs text-muted-foreground">
            Передаётся в NorthLine как add-on. 0 = без LTE.
          </p>
        </div>
      </div>

      <div className="space-y-1">
        <Label>Описание (HTML)</Label>
        <TipTapEditor
          value={desc ?? ''}
          onChange={(html) => form.setValue('description_html', html, { shouldDirty: true })}
        />
      </div>

      <div className="flex items-center gap-3">
        <Switch
          checked={isActive}
          onCheckedChange={(v) => form.setValue('is_active', v, { shouldDirty: true })}
        />
        <Label className="cursor-pointer">Активен</Label>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button type="submit" disabled={createMut.isPending || updateMut.isPending}>
          {(createMut.isPending || updateMut.isPending) && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          {isNew ? 'Создать' : 'Сохранить'}
        </Button>
        {!isNew && (
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              if (window.confirm('Удалить тариф? Это действие нельзя отменить.')) {
                removeMut.mutate(tariff!.id);
              }
            }}
            disabled={removeMut.isPending}
          >
            <Trash2 className="h-4 w-4" />
            Удалить
          </Button>
        )}
      </div>

      {!isNew && tariff && <DurationsMatrix tariff={tariff} />}
    </form>
  );
}

interface DurationsMatrixProps {
  tariff: Tariff;
}

function DurationsMatrix({ tariff }: DurationsMatrixProps) {
  const qc = useQueryClient();
  const [editingId, setEditingId] = useState<number | 'new' | null>(null);
  const [draft, setDraft] = useState<{
    days: number;
    price_kopecks: number;
    is_hot: boolean;
  }>({ days: 30, price_kopecks: 19900, is_hot: false });

  const addMut = useMutation({
    mutationFn: () =>
      addDuration(tariff.id, {
        days: draft.days,
        price_kopecks: draft.price_kopecks,
        is_hot: draft.is_hot,
      }),
    onSuccess: () => {
      toast.success('Цена добавлена');
      setEditingId(null);
      void qc.invalidateQueries({ queryKey: ['tariffs'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });
  const updMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<TariffDuration> }) =>
      updateDuration(tariff.id, id, payload),
    onSuccess: () => {
      toast.success('Цена обновлена');
      setEditingId(null);
      void qc.invalidateQueries({ queryKey: ['tariffs'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });
  const delMut = useMutation({
    mutationFn: (id: number) => removeDuration(tariff.id, id),
    onSuccess: () => {
      toast.success('Цена удалена');
      void qc.invalidateQueries({ queryKey: ['tariffs'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const startEdit = (d: TariffDuration) => {
    setEditingId(d.id);
    setDraft({ days: d.days, price_kopecks: d.price_kopecks, is_hot: d.is_hot });
  };

  return (
    <div className="space-y-2 rounded-md border border-border p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Матрица цен</h3>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            setEditingId('new');
            setDraft({ days: 30, price_kopecks: 19900, is_hot: false });
          }}
        >
          <Plus className="h-4 w-4" />
          Добавить
        </Button>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Дней</TableHead>
            <TableHead>Цена (коп.)</TableHead>
            <TableHead>Hot</TableHead>
            <TableHead className="w-32 text-right">Действия</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tariff.durations.map((d) => {
            const editing = editingId === d.id;
            return (
              <TableRow key={d.id}>
                <TableCell>
                  {editing ? (
                    <Input
                      type="number"
                      value={draft.days}
                      onChange={(e) => setDraft((s) => ({ ...s, days: +e.target.value }))}
                      className="h-8 w-24"
                    />
                  ) : (
                    d.days
                  )}
                </TableCell>
                <TableCell>
                  {editing ? (
                    <Input
                      type="number"
                      value={draft.price_kopecks}
                      onChange={(e) =>
                        setDraft((s) => ({ ...s, price_kopecks: +e.target.value }))
                      }
                      className="h-8 w-32"
                    />
                  ) : (
                    <span className="font-mono text-xs">{d.price_kopecks}</span>
                  )}
                </TableCell>
                <TableCell>
                  {editing ? (
                    <Switch
                      checked={draft.is_hot}
                      onCheckedChange={(v) => setDraft((s) => ({ ...s, is_hot: v }))}
                    />
                  ) : d.is_hot ? (
                    <Badge variant="warning">hot</Badge>
                  ) : (
                    '—'
                  )}
                </TableCell>
                <TableCell className="text-right">
                  {editing ? (
                    <div className="flex justify-end gap-1">
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={() => updMut.mutate({ id: d.id, payload: draft })}
                        disabled={updMut.isPending}
                      >
                        <Check className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={() => setEditingId(null)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex justify-end gap-1">
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={() => startEdit(d)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={() => {
                          if (window.confirm('Удалить эту цену?')) {
                            delMut.mutate(d.id);
                          }
                        }}
                        disabled={delMut.isPending}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
          {editingId === 'new' && (
            <TableRow>
              <TableCell>
                <Input
                  type="number"
                  value={draft.days}
                  onChange={(e) => setDraft((s) => ({ ...s, days: +e.target.value }))}
                  className="h-8 w-24"
                />
              </TableCell>
              <TableCell>
                <Input
                  type="number"
                  value={draft.price_kopecks}
                  onChange={(e) =>
                    setDraft((s) => ({ ...s, price_kopecks: +e.target.value }))
                  }
                  className="h-8 w-32"
                />
              </TableCell>
              <TableCell>
                <Switch
                  checked={draft.is_hot}
                  onCheckedChange={(v) => setDraft((s) => ({ ...s, is_hot: v }))}
                />
              </TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-1">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    onClick={() => addMut.mutate()}
                    disabled={addMut.isPending}
                  >
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    onClick={() => setEditingId(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          )}
          {tariff.durations.length === 0 && editingId !== 'new' && (
            <TableRow>
              <TableCell colSpan={4} className="h-16 text-center text-muted-foreground">
                Цен ещё нет. Добавьте первую.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
