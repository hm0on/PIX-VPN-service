import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowLeft,
  Ban,
  Copy,
  ExternalLink,
  Loader2,
  Trash2,
} from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import { subscriptionsApi } from '@/api/endpoints/subscriptions';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { formatBytes, formatDateTime, truncate } from '@/utils/format';

interface FieldProps {
  label: string;
  children: React.ReactNode;
}
function Field({ label, children }: FieldProps) {
  return (
    <div className="space-y-1">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

export default function SubDetail() {
  const { id: idStr } = useParams<{ id: string }>();
  const id = Number(idStr);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [deactOpen, setDeactOpen] = useState(false);
  const [deactReason, setDeactReason] = useState('');
  const [confirmDevice, setConfirmDevice] = useState<string | null>(null);

  const subQuery = useQuery({
    queryKey: ['sub', id],
    queryFn: () => subscriptionsApi.get(id),
    enabled: Number.isFinite(id),
  });

  const infoQuery = useQuery({
    queryKey: ['sub', id, 'info'],
    queryFn: () => subscriptionsApi.info(id),
    enabled: Number.isFinite(id),
    retry: false,
  });

  const isInfoUpstreamDown =
    infoQuery.isError &&
    axios.isAxiosError(infoQuery.error) &&
    infoQuery.error.response?.status === 502;

  const deactivateMutation = useMutation({
    mutationFn: () =>
      subscriptionsApi.deactivate(id, { reason: deactReason.trim() }),
    onSuccess: () => {
      toast.success('Ключ деактивирован');
      setDeactOpen(false);
      setDeactReason('');
      void queryClient.invalidateQueries({ queryKey: ['sub', id] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const removeDeviceMutation = useMutation({
    mutationFn: (deviceId: string) => subscriptionsApi.removeDevice(id, deviceId),
    onSuccess: () => {
      toast.success('Устройство удалено');
      setConfirmDevice(null);
      void queryClient.invalidateQueries({ queryKey: ['sub', id, 'info'] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  if (!Number.isFinite(id)) {
    return <p className="text-sm text-destructive">Некорректный ID подписки.</p>;
  }

  const sub = subQuery.data;
  const info = infoQuery.data;

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Скопировано');
    } catch {
      toast.error('Не удалось скопировать');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => navigate('/subscriptions')}>
          <ArrowLeft className="h-4 w-4" />
          К списку
        </Button>
        <h1 className="text-2xl font-bold tracking-tight">Подписка #{id}</h1>
        {sub && (
          <Badge
            variant={
              sub.status === 'active'
                ? 'success'
                : sub.status === 'expired'
                  ? 'warning'
                  : sub.status === 'deactivated'
                    ? 'destructive'
                    : 'muted'
            }
          >
            {sub.status}
          </Badge>
        )}
      </div>

      {subQuery.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : subQuery.isError || !sub ? (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Не удалось загрузить: {getErrorMessage(subQuery.error)}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle>Параметры</CardTitle>
                <CardDescription>
                  Владелец, тариф, статус, ключ доступа
                </CardDescription>
              </div>
              {sub.status !== 'deactivated' && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setDeactOpen(true)}
                >
                  <Ban className="h-4 w-4" />
                  Деактивировать
                </Button>
              )}
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="ID">
                  <span className="font-mono">#{sub.id}</span>
                </Field>
                <Field label="Владелец">
                  <Link
                    to={`/users/${sub.user_id}`}
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    {sub.user_username
                      ? '@' + sub.user_username
                      : `tg_id ${sub.user_tg_id}`}
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                </Field>
                <Field label="Тариф">
                  {sub.tariff_name ?? sub.tariff_code ?? '—'}
                </Field>
                <Field label="Устройств">{sub.devices}</Field>
                <Field label="Длительность, дней">{sub.days ?? '—'}</Field>
                <Field label="Триал?">
                  {sub.is_free_trial ? 'Да' : 'Нет'}
                </Field>
                <Field label="Создана">{formatDateTime(sub.created_at)}</Field>
                <Field label="Истекает">{formatDateTime(sub.expires_at)}</Field>
                <Field label="Деактивирована">
                  {formatDateTime(sub.deactivated_at)}
                </Field>
              </div>

              {sub.deactivation_reason && (
                <Field label="Причина деактивации">
                  <span className="text-sm">{sub.deactivation_reason}</span>
                </Field>
              )}

              {sub.key_url && (
                <Field label="Ключ доступа">
                  <div className="flex items-center gap-2">
                    <code className="block max-w-full break-all rounded-md border border-border bg-muted p-2 text-xs">
                      {sub.key_url}
                    </code>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => handleCopy(sub.key_url!)}
                      title="Скопировать"
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  </div>
                </Field>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Статистика трафика</CardTitle>
              <CardDescription>NorthLine.get_key</CardDescription>
            </CardHeader>
            <CardContent>
              {infoQuery.isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : isInfoUpstreamDown || infoQuery.isError ? (
                <p className="text-sm text-muted-foreground">
                  Статистика недоступна
                </p>
              ) : info ? (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <Field label="Трафик">
                    {info.traffic_bytes != null
                      ? formatBytes(info.traffic_bytes)
                      : 'Статистика недоступна'}
                  </Field>
                  <Field label="Квота, ГБ">
                    {info.traffic_quota_gb != null
                      ? `${info.traffic_quota_gb} ГБ`
                      : '—'}
                  </Field>
                  <Field label="LTE-трафик">
                    {info.lte_traffic_bytes != null
                      ? formatBytes(info.lte_traffic_bytes)
                      : 'Статистика недоступна'}
                  </Field>
                  <Field label="Истекает (по NL)">
                    {formatDateTime(info.expires_at)}
                  </Field>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Устройства</CardTitle>
              <CardDescription>
                {info?.devices_used != null && info?.devices_total != null
                  ? `Подключено: ${info.devices_used} из ${info.devices_total}`
                  : 'Активные подключения'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {infoQuery.isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : isInfoUpstreamDown || infoQuery.isError ? (
                <p className="text-sm text-muted-foreground">
                  Список устройств недоступен
                </p>
              ) : (info?.devices ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {info?.devices_used != null && info.devices_used > 0
                    ? `Активно: ${info.devices_used}. Поставщик пока не возвращает их перечень — посмотрите в панели NorthLine.`
                    : 'Нет подключённых устройств.'}
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>Имя</TableHead>
                      <TableHead>Последний онлайн</TableHead>
                      <TableHead>IP</TableHead>
                      <TableHead className="w-16 text-right">Действия</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(info?.devices ?? []).map((d) => (
                      <TableRow key={d.id}>
                        <TableCell className="font-mono text-xs">
                          {truncate(d.id, 24)}
                        </TableCell>
                        <TableCell>{d.name ?? '—'}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(d.last_seen_at)}
                        </TableCell>
                        <TableCell className="text-xs">{d.ip ?? '—'}</TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setConfirmDevice(d.id)}
                            disabled={removeDeviceMutation.isPending}
                            aria-label="Удалить устройство"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {/* Deactivate dialog */}
      <Dialog open={deactOpen} onOpenChange={setDeactOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Деактивировать ключ</DialogTitle>
            <DialogDescription>
              Юзеру отправится уведомление с указанной причиной. NorthLine.deactivate_key
              будет вызван немедленно.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="deact-reason">Причина</Label>
            <Textarea
              id="deact-reason"
              rows={3}
              value={deactReason}
              onChange={(e) => setDeactReason(e.target.value)}
              placeholder="Например: возврат средств, нарушение правил…"
              disabled={deactivateMutation.isPending}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeactOpen(false)}
              disabled={deactivateMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => deactivateMutation.mutate()}
              disabled={deactivateMutation.isPending || !deactReason.trim()}
            >
              {deactivateMutation.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Деактивировать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Device delete confirm */}
      <Dialog
        open={Boolean(confirmDevice)}
        onOpenChange={(o) => !o && setConfirmDevice(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить устройство?</DialogTitle>
            <DialogDescription>
              Устройство {confirmDevice ? <code>{truncate(confirmDevice, 32)}</code> : ''}{' '}
              будет отключено от ключа через NorthLine.remove_device.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmDevice(null)}
              disabled={removeDeviceMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                confirmDevice && removeDeviceMutation.mutate(confirmDevice)
              }
              disabled={removeDeviceMutation.isPending}
            >
              {removeDeviceMutation.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Удалить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
