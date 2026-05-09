import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  CalendarRange,
  TrendingUp,
  Users,
  Wallet,
} from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { northlineApi } from '@/api/endpoints/northline';
import { statsApi } from '@/api/endpoints/stats';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { config } from '@/config';
import { cn } from '@/lib/utils';
import {
  formatDateTime,
  formatNumber,
  formatRub,
  truncate,
} from '@/utils/format';
import type { Period } from '@/types/api';

const PERIODS: { value: Period; label: string }[] = [
  { value: '30d', label: '30 дней' },
  { value: '90d', label: '90 дней' },
  { value: '365d', label: '365 дней' },
];

interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon: typeof Wallet;
  loading?: boolean;
}

function KpiCard({ title, value, subtitle, icon: Icon, loading }: KpiCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-32" />
        ) : (
          <>
            <div className="text-2xl font-bold">{value}</div>
            {subtitle && (
              <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

interface PeriodToggleProps {
  value: Period;
  onChange: (p: Period) => void;
}

function PeriodToggle({ value, onChange }: PeriodToggleProps) {
  return (
    <div className="inline-flex rounded-md border border-border bg-background p-1">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          type="button"
          onClick={() => onChange(p.value)}
          className={cn(
            'rounded-sm px-3 py-1 text-xs font-medium transition-colors',
            value === p.value
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const [revenuePeriod, setRevenuePeriod] = useState<Period>('30d');
  const [usersPeriod, setUsersPeriod] = useState<Period>('30d');

  const kpiQuery = useQuery({
    queryKey: ['dashboard', 'kpi'],
    queryFn: statsApi.dashboard,
    refetchInterval: config.dashboardPollMs,
  });

  const revenueQuery = useQuery({
    queryKey: ['dashboard', 'revenue', revenuePeriod],
    queryFn: () => statsApi.revenue(revenuePeriod),
    refetchInterval: config.dashboardPollMs,
  });

  const usersQuery = useQuery({
    queryKey: ['dashboard', 'users-chart', usersPeriod],
    queryFn: () => statsApi.users(usersPeriod),
    refetchInterval: config.dashboardPollMs,
  });

  const recentPaymentsQuery = useQuery({
    queryKey: ['dashboard', 'recent-payments'],
    queryFn: () => statsApi.recentPayments(10),
    refetchInterval: config.dashboardPollMs,
  });

  const recentUsersQuery = useQuery({
    queryKey: ['dashboard', 'recent-users'],
    queryFn: () => statsApi.recentUsers(10),
    refetchInterval: config.dashboardPollMs,
  });

  // NorthLine reseller balance — surfaced as a KPI on the dashboard so ops
  // can spot a near-empty balance before it bites the next purchase.
  const resellerQuery = useQuery({
    queryKey: ['dashboard', 'reseller'],
    queryFn: northlineApi.profile,
    refetchInterval: 30_000,
  });

  const resellerBalanceText = resellerQuery.data
    ? new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(resellerQuery.data.balance_rub)
    : '—';
  const resellerSubtitle = resellerQuery.dataUpdatedAt
    ? `Обновлено ${formatDateTime(new Date(resellerQuery.dataUpdatedAt).toISOString())}`
    : undefined;

  const kpi = kpiQuery.data;
  const revenueData = (revenueQuery.data ?? []).map((p) => ({
    date: p.date,
    amount: p.amount_kop / 100,
  }));
  const usersData = usersQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Дашборд</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ключевые метрики обновляются автоматически каждые 60 секунд.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Баланс NorthLine"
          value={resellerBalanceText}
          subtitle={resellerSubtitle}
          icon={Wallet}
          loading={resellerQuery.isLoading}
        />
        <KpiCard
          title="Активных подписок"
          value={formatNumber(kpi?.active_subscriptions)}
          subtitle={
            kpi ? `Пользователей: ${formatNumber(kpi.users_total)}` : undefined
          }
          icon={Activity}
          loading={kpiQuery.isLoading}
        />
        <KpiCard
          title="Прибыль за месяц"
          value={formatRub(kpi?.revenue_month_kop)}
          icon={Users}
          loading={kpiQuery.isLoading}
        />
        <KpiCard
          title="Прибыль за сегодня"
          value={formatRub(kpi?.revenue_today_kop)}
          icon={TrendingUp}
          loading={kpiQuery.isLoading}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>Прибыль</CardTitle>
              <CardDescription>Выручка по дням, ₽</CardDescription>
            </div>
            <PeriodToggle value={revenuePeriod} onChange={setRevenuePeriod} />
          </CardHeader>
          <CardContent>
            {revenueQuery.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : revenueData.length === 0 ? (
              <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                Нет данных за период
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={256}>
                <LineChart data={revenueData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="date" stroke="currentColor" tick={{ fontSize: 11 }} />
                  <YAxis stroke="currentColor" tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--popover))',
                      borderColor: 'hsl(var(--border))',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: 'hsl(var(--foreground))' }}
                  />
                  <Line
                    type="monotone"
                    dataKey="amount"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>Регистрации</CardTitle>
              <CardDescription>Новые пользователи по дням</CardDescription>
            </div>
            <PeriodToggle value={usersPeriod} onChange={setUsersPeriod} />
          </CardHeader>
          <CardContent>
            {usersQuery.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : usersData.length === 0 ? (
              <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                Нет данных за период
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={256}>
                <LineChart data={usersData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="date" stroke="currentColor" tick={{ fontSize: 11 }} />
                  <YAxis stroke="currentColor" tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--popover))',
                      borderColor: 'hsl(var(--border))',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: 'hsl(var(--foreground))' }}
                  />
                  <Line
                    type="monotone"
                    dataKey="count"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Последние платежи</CardTitle>
            <CardDescription>10 свежих платежей</CardDescription>
          </CardHeader>
          <CardContent>
            {recentPaymentsQuery.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (recentPaymentsQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Платежей нет.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Дата</TableHead>
                    <TableHead>Юзер</TableHead>
                    <TableHead className="text-right">Сумма</TableHead>
                    <TableHead>Статус</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(recentPaymentsQuery.data ?? []).map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(p.created_at)}
                      </TableCell>
                      <TableCell>
                        <Link
                          to={`/users/${p.user_id}`}
                          className="text-primary hover:underline"
                        >
                          {p.user_username
                            ? '@' + truncate(p.user_username, 18)
                            : `tg_id ${p.user_tg_id}`}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatRub(p.amount_kop)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={p.status === 'paid' ? 'success' : 'muted'}
                        >
                          {p.status}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Последние регистрации</CardTitle>
            <CardDescription>Новые пользователи бота</CardDescription>
          </CardHeader>
          <CardContent>
            {recentUsersQuery.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (recentUsersQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Пока пусто.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Когда</TableHead>
                    <TableHead>Юзер</TableHead>
                    <TableHead>Имя</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(recentUsersQuery.data ?? []).map((u) => (
                    <TableRow key={u.id}>
                      <TableCell className="text-xs text-muted-foreground">
                        <CalendarRange className="mr-1 inline h-3 w-3" />
                        {formatDateTime(u.created_at)}
                      </TableCell>
                      <TableCell>
                        <Link
                          to={`/users/${u.id}`}
                          className="text-primary hover:underline"
                        >
                          {u.username ? '@' + u.username : `tg_id ${u.tg_id}`}
                        </Link>
                      </TableCell>
                      <TableCell>{u.first_name ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
