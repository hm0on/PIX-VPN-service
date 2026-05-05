import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowLeft,
  Ban,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Wallet,
} from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import { usersApi } from '@/api/endpoints/users';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { formatDateTime, formatNumber, formatRub } from '@/utils/format';
import type { UserTicket } from '@/types/api';

function StatusBadge({ banned }: { banned: boolean }) {
  return banned ? (
    <Badge variant="destructive">Заблокирован</Badge>
  ) : (
    <Badge variant="success">Активен</Badge>
  );
}

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

export default function UserDetail() {
  const { id: idStr } = useParams<{ id: string }>();
  const id = Number(idStr);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [banOpen, setBanOpen] = useState(false);
  const [banReason, setBanReason] = useState('');
  const [adjOpen, setAdjOpen] = useState(false);
  const [adjAmount, setAdjAmount] = useState('');
  const [adjReason, setAdjReason] = useState('');
  const [ticketModal, setTicketModal] = useState<UserTicket | null>(null);

  const userQuery = useQuery({
    queryKey: ['user', id],
    queryFn: () => usersApi.get(id),
    enabled: Number.isFinite(id),
  });

  const paymentsQuery = useQuery({
    queryKey: ['user', id, 'payments'],
    queryFn: () => usersApi.payments(id),
    enabled: Number.isFinite(id),
  });

  const subsQuery = useQuery({
    queryKey: ['user', id, 'subscriptions'],
    queryFn: () => usersApi.subscriptions(id),
    enabled: Number.isFinite(id),
  });

  const ticketsQuery = useQuery({
    queryKey: ['user', id, 'tickets'],
    queryFn: () => usersApi.tickets(id),
    enabled: Number.isFinite(id),
  });

  const referralsQuery = useQuery({
    queryKey: ['user', id, 'referrals'],
    queryFn: () => usersApi.referrals(id),
    enabled: Number.isFinite(id),
  });

  const balanceQuery = useQuery({
    queryKey: ['user', id, 'balance'],
    queryFn: () => usersApi.balanceHistory(id),
    enabled: Number.isFinite(id),
  });

  const invalidateUser = () => {
    void queryClient.invalidateQueries({ queryKey: ['user', id] });
  };

  const banMutation = useMutation({
    mutationFn: () => usersApi.ban(id, { reason: banReason.trim() }),
    onSuccess: () => {
      toast.success('Пользователь заблокирован');
      setBanOpen(false);
      setBanReason('');
      invalidateUser();
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const unbanMutation = useMutation({
    mutationFn: () => usersApi.unban(id),
    onSuccess: () => {
      toast.success('Блокировка снята');
      invalidateUser();
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const adjustMutation = useMutation({
    mutationFn: () => {
      const amount = Number(adjAmount);
      if (!Number.isFinite(amount) || amount === 0) {
        return Promise.reject(new Error('Укажите сумму в копейках (≠ 0)'));
      }
      if (!adjReason.trim()) return Promise.reject(new Error('Укажите причину'));
      return usersApi.balanceAdjust(id, {
        amount_kop: Math.trunc(amount),
        reason: adjReason.trim(),
      });
    },
    onSuccess: () => {
      toast.success('Баланс изменён');
      setAdjOpen(false);
      setAdjAmount('');
      setAdjReason('');
      invalidateUser();
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  if (!Number.isFinite(id)) {
    return <p className="text-sm text-destructive">Некорректный ID пользователя.</p>;
  }

  const user = userQuery.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => navigate('/users')}>
          <ArrowLeft className="h-4 w-4" />
          К списку
        </Button>
        <h1 className="text-2xl font-bold tracking-tight">
          Пользователь #{id}
        </h1>
        {user && <StatusBadge banned={user.is_banned} />}
      </div>

      {userQuery.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : userQuery.isError || !user ? (
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            Не удалось загрузить пользователя: {getErrorMessage(userQuery.error)}
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="profile" className="w-full">
          <TabsList className="flex-wrap">
            <TabsTrigger value="profile">Профиль</TabsTrigger>
            <TabsTrigger value="payments">Покупки</TabsTrigger>
            <TabsTrigger value="subs">Подписки</TabsTrigger>
            <TabsTrigger value="tickets">Тикеты</TabsTrigger>
            <TabsTrigger value="referrals">Рефералы</TabsTrigger>
            <TabsTrigger value="balance">Баланс</TabsTrigger>
          </TabsList>

          {/* Profile */}
          <TabsContent value="profile">
            <Card>
              <CardHeader>
                <CardTitle>Профиль</CardTitle>
                <CardDescription>Базовая информация и действия</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <Field label="tg_id">
                    <span className="font-mono">{user.tg_id}</span>
                  </Field>
                  <Field label="username">
                    {user.username ? '@' + user.username : '—'}
                  </Field>
                  <Field label="Имя">
                    {[user.first_name, user.last_name].filter(Boolean).join(' ') || '—'}
                  </Field>
                  <Field label="Язык">{user.language_code ?? '—'}</Field>
                  <Field label="Баланс">
                    <span className="font-semibold">{formatRub(user.balance_kop)}</span>
                  </Field>
                  <Field label="Активных подписок">
                    {formatNumber(user.active_subscriptions_count)}
                  </Field>
                  <Field label="Реферер">
                    {user.referrer_id ? (
                      <Link
                        to={`/users/${user.referrer_id}`}
                        className="text-primary hover:underline"
                      >
                        #{user.referrer_id}
                      </Link>
                    ) : (
                      '—'
                    )}
                  </Field>
                  <Field label="Создан">{formatDateTime(user.created_at)}</Field>
                  <Field label="Статус">
                    <div className="flex flex-col gap-1">
                      <StatusBadge banned={user.is_banned} />
                      {user.is_banned && user.ban_reason && (
                        <span className="text-xs text-muted-foreground">
                          {user.ban_reason}
                        </span>
                      )}
                    </div>
                  </Field>
                </div>

                <div className="flex flex-wrap gap-2">
                  {user.is_banned ? (
                    <Button
                      variant="outline"
                      onClick={() => unbanMutation.mutate()}
                      disabled={unbanMutation.isPending}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Разблокировать
                    </Button>
                  ) : (
                    <Button
                      variant="destructive"
                      onClick={() => setBanOpen(true)}
                    >
                      <Ban className="h-4 w-4" />
                      Заблокировать
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => setAdjOpen(true)}>
                    <Wallet className="h-4 w-4" />
                    Изменить баланс
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Payments */}
          <TabsContent value="payments">
            <Card>
              <CardHeader>
                <CardTitle>Покупки</CardTitle>
                <CardDescription>Все платежи пользователя</CardDescription>
              </CardHeader>
              <CardContent>
                {paymentsQuery.isLoading ? (
                  <Skeleton className="h-40 w-full" />
                ) : (paymentsQuery.data ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">Платежей нет.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Дата</TableHead>
                        <TableHead className="text-right">Сумма</TableHead>
                        <TableHead>Провайдер</TableHead>
                        <TableHead>Статус</TableHead>
                        <TableHead>Подписка</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(paymentsQuery.data ?? []).map((p) => (
                        <TableRow key={p.id}>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDateTime(p.created_at)}
                          </TableCell>
                          <TableCell className="text-right font-medium">
                            {formatRub(p.amount_kop)}
                          </TableCell>
                          <TableCell>{p.provider}</TableCell>
                          <TableCell>
                            <Badge
                              variant={p.status === 'paid' ? 'success' : 'muted'}
                            >
                              {p.status}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {p.subscription_id ? (
                              <Link
                                to={`/subscriptions/${p.subscription_id}`}
                                className="inline-flex items-center gap-1 text-primary hover:underline"
                              >
                                #{p.subscription_id}
                                <ExternalLink className="h-3 w-3" />
                              </Link>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Subscriptions */}
          <TabsContent value="subs">
            <Card>
              <CardHeader>
                <CardTitle>Подписки</CardTitle>
                <CardDescription>
                  Все ключи (включая истёкшие и деактивированные)
                </CardDescription>
              </CardHeader>
              <CardContent>
                {subsQuery.isLoading ? (
                  <Skeleton className="h-40 w-full" />
                ) : (subsQuery.data ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">Подписок нет.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>ID</TableHead>
                        <TableHead>Тариф</TableHead>
                        <TableHead className="text-right">Устройства</TableHead>
                        <TableHead>Статус</TableHead>
                        <TableHead>Истекает</TableHead>
                        <TableHead>Создана</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(subsQuery.data ?? []).map((s) => (
                        <TableRow
                          key={s.id}
                          className="cursor-pointer"
                          onClick={() => navigate(`/subscriptions/${s.id}`)}
                        >
                          <TableCell className="font-mono">#{s.id}</TableCell>
                          <TableCell>{s.tariff_name ?? s.tariff_code ?? '—'}</TableCell>
                          <TableCell className="text-right">{s.devices}</TableCell>
                          <TableCell>
                            <Badge
                              variant={s.status === 'active' ? 'success' : 'muted'}
                            >
                              {s.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDateTime(s.expires_at)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDateTime(s.created_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Tickets */}
          <TabsContent value="tickets">
            <Card>
              <CardHeader>
                <CardTitle>Тикеты</CardTitle>
                <CardDescription>Обращения пользователя</CardDescription>
              </CardHeader>
              <CardContent>
                {ticketsQuery.isLoading ? (
                  <Skeleton className="h-40 w-full" />
                ) : (ticketsQuery.data ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">Тикетов нет.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Код</TableHead>
                        <TableHead>Тип</TableHead>
                        <TableHead>Статус</TableHead>
                        <TableHead>Открыт</TableHead>
                        <TableHead>Закрыт</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(ticketsQuery.data ?? []).map((t) => (
                        <TableRow
                          key={t.id}
                          className="cursor-pointer"
                          onClick={() => setTicketModal(t)}
                        >
                          <TableCell className="font-mono">{t.code}</TableCell>
                          <TableCell>{t.kind}</TableCell>
                          <TableCell>
                            <Badge
                              variant={t.status === 'open' ? 'warning' : 'muted'}
                            >
                              {t.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDateTime(t.created_at)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDateTime(t.closed_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Referrals */}
          <TabsContent value="referrals">
            <Card>
              <CardHeader>
                <CardTitle>Рефералы</CardTitle>
                <CardDescription>
                  Кто пригласил и кого пригласил пользователь
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {referralsQuery.isLoading ? (
                  <Skeleton className="h-40 w-full" />
                ) : (
                  <>
                    <div>
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Пригласил
                      </div>
                      {referralsQuery.data?.referrer ? (
                        <Link
                          to={`/users/${referralsQuery.data.referrer.id}`}
                          className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          {referralsQuery.data.referrer.username
                            ? '@' + referralsQuery.data.referrer.username
                            : `tg_id ${referralsQuery.data.referrer.tg_id}`}
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                      ) : (
                        <p className="mt-1 text-sm text-muted-foreground">—</p>
                      )}
                    </div>

                    <div>
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Приглашённые
                      </div>
                      {(referralsQuery.data?.invited ?? []).length === 0 ? (
                        <p className="mt-2 text-sm text-muted-foreground">Никого нет.</p>
                      ) : (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>tg_id</TableHead>
                              <TableHead>username</TableHead>
                              <TableHead>Создан</TableHead>
                              <TableHead>Платил?</TableHead>
                              <TableHead className="text-right">Бонус</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {referralsQuery.data!.invited.map((r) => (
                              <TableRow
                                key={r.id}
                                className="cursor-pointer"
                                onClick={() => navigate(`/users/${r.id}`)}
                              >
                                <TableCell className="font-mono text-xs">
                                  {r.tg_id}
                                </TableCell>
                                <TableCell>
                                  {r.username ? '@' + r.username : '—'}
                                </TableCell>
                                <TableCell className="text-xs text-muted-foreground">
                                  {formatDateTime(r.created_at)}
                                </TableCell>
                                <TableCell>
                                  {r.has_paid ? (
                                    <Badge variant="success">Да</Badge>
                                  ) : (
                                    <Badge variant="muted">Нет</Badge>
                                  )}
                                </TableCell>
                                <TableCell className="text-right">
                                  {formatRub(r.bonus_kop)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Balance */}
          <TabsContent value="balance">
            <Card>
              <CardHeader>
                <CardTitle>История баланса</CardTitle>
                <CardDescription>
                  Все операции по `balance_transactions`
                </CardDescription>
              </CardHeader>
              <CardContent>
                {balanceQuery.isLoading ? (
                  <Skeleton className="h-40 w-full" />
                ) : (balanceQuery.data ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">Записей нет.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Дата</TableHead>
                        <TableHead className="text-right">Сумма</TableHead>
                        <TableHead>Причина</TableHead>
                        <TableHead>Комментарий</TableHead>
                        <TableHead>Админ</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(balanceQuery.data ?? []).map((tx) => (
                        <TableRow key={tx.id}>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDateTime(tx.created_at)}
                          </TableCell>
                          <TableCell
                            className={
                              'text-right font-medium ' +
                              (tx.amount_kop >= 0
                                ? 'text-emerald-500'
                                : 'text-destructive')
                            }
                          >
                            {tx.amount_kop >= 0 ? '+' : ''}
                            {formatRub(tx.amount_kop)}
                          </TableCell>
                          <TableCell>{tx.reason}</TableCell>
                          <TableCell className="max-w-[260px] truncate text-xs text-muted-foreground">
                            {tx.comment ?? '—'}
                          </TableCell>
                          <TableCell className="text-xs">
                            {tx.admin_label ?? '—'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}

      {/* Ban dialog */}
      <Dialog open={banOpen} onOpenChange={setBanOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Заблокировать пользователя</DialogTitle>
            <DialogDescription>
              Юзеру отправится уведомление с указанной причиной. Действие можно
              отменить разблокировкой.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="ban-reason">Причина</Label>
            <Textarea
              id="ban-reason"
              rows={3}
              value={banReason}
              onChange={(e) => setBanReason(e.target.value)}
              placeholder="Напр. нарушение правил…"
              disabled={banMutation.isPending}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setBanOpen(false)}
              disabled={banMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => banMutation.mutate()}
              disabled={banMutation.isPending || !banReason.trim()}
            >
              {banMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Заблокировать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Balance adjust dialog */}
      <Dialog open={adjOpen} onOpenChange={setAdjOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Изменить баланс</DialogTitle>
            <DialogDescription>
              Сумма указывается в копейках (целое, может быть отрицательным).
              Запишется в balance_transactions с reason=&apos;admin_adjust&apos;.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="adj-amount">Сумма, копейки (signed)</Label>
              <Input
                id="adj-amount"
                type="number"
                value={adjAmount}
                onChange={(e) => setAdjAmount(e.target.value)}
                placeholder="например, -10000 (минус 100 ₽)"
                disabled={adjustMutation.isPending}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="adj-reason">Причина</Label>
              <Textarea
                id="adj-reason"
                rows={2}
                value={adjReason}
                onChange={(e) => setAdjReason(e.target.value)}
                placeholder="Кратко опишите, для аудита"
                disabled={adjustMutation.isPending}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setAdjOpen(false)}
              disabled={adjustMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              onClick={() => adjustMutation.mutate()}
              disabled={
                adjustMutation.isPending ||
                !adjAmount ||
                Number(adjAmount) === 0 ||
                !adjReason.trim()
              }
            >
              {adjustMutation.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Применить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Ticket modal */}
      <Dialog open={Boolean(ticketModal)} onOpenChange={(o) => !o && setTicketModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Тикет {ticketModal?.code}</DialogTitle>
            <DialogDescription>
              {ticketModal?.kind} · {ticketModal?.status}
            </DialogDescription>
          </DialogHeader>
          {ticketModal && (
            <div className="space-y-2 text-sm">
              <p>
                Топик в Telegram-группе:{' '}
                <span className="font-mono">
                  ID {ticketModal.topic_thread_id ?? '—'}
                </span>
              </p>
              {ticketModal.group_link && (
                <a
                  href={ticketModal.group_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  Открыть в Telegram
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
              <p className="text-xs text-muted-foreground">
                Открыт: {formatDateTime(ticketModal.created_at)}
              </p>
              {ticketModal.closed_at && (
                <p className="text-xs text-muted-foreground">
                  Закрыт: {formatDateTime(ticketModal.closed_at)}
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setTicketModal(null)}>Закрыть</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
