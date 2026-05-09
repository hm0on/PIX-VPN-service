import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { Clock, Search } from 'lucide-react';

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
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { DatePicker } from '@/components/DatePicker';
import { Pagination } from '@/components/Pagination';
import { SortHeader } from '@/components/SortHeader';
import { useDebounce } from '@/hooks/use-debounce';
import { useUrlFilters } from '@/hooks/useUrlFilters';
import { formatDateTime, truncate } from '@/utils/format';
import type { SubscriptionListParams } from '@/types/api';

const PER_PAGE = 50;

const STATUS_OPTIONS = [
  { value: '', label: 'Все статусы' },
  { value: 'active', label: 'Активные' },
  { value: 'expired', label: 'Истёкшие' },
  { value: 'deactivated', label: 'Деактивированные' },
  { value: 'pending', label: 'Pending' },
];

const TRIAL_OPTIONS = [
  { value: '', label: 'Все' },
  { value: '1', label: 'Только триал' },
  { value: '0', label: 'Без триала' },
];

interface SubsFilters {
  status: string;
  tariff_id: string;
  is_free_trial: string;
  q: string;
  expires_from: string;
  expires_to: string;
  page: number;
  page_size: number;
  sort: string;
  [key: string]: string | number | boolean | undefined;
}

const DEFAULTS: SubsFilters = {
  status: '',
  tariff_id: '',
  is_free_trial: '',
  q: '',
  expires_from: '',
  expires_to: '',
  page: 1,
  page_size: PER_PAGE,
  sort: 'created_at:desc',
};

const EXPIRE_SOON_DAYS = 3;

function isExpiringSoon(expiresAt: string | null, status: string): boolean {
  if (!expiresAt) return false;
  if (status !== 'active') return false;
  const ts = new Date(expiresAt).getTime();
  if (Number.isNaN(ts)) return false;
  const diffMs = ts - Date.now();
  return diffMs > 0 && diffMs < EXPIRE_SOON_DAYS * 24 * 3600 * 1000;
}

export default function SubsList() {
  const navigate = useNavigate();
  const { filters, setFilter, reset } = useUrlFilters({ defaults: DEFAULTS });

  // Local mirrors for text inputs so we can debounce without bouncing through
  // the URL on every keystroke.
  const [qLocal, setQLocal] = useState(filters.q);
  const [tariffLocal, setTariffLocal] = useState(filters.tariff_id);
  const debouncedQ = useDebounce(qLocal, 300);
  const debouncedTariff = useDebounce(tariffLocal, 300);

  useEffect(() => {
    if (debouncedQ !== filters.q) setFilter('q', debouncedQ, { resetPage: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);
  useEffect(() => {
    if (debouncedTariff !== filters.tariff_id)
      setFilter('tariff_id', debouncedTariff, { resetPage: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedTariff]);
  useEffect(() => setQLocal(filters.q), [filters.q]);
  useEffect(() => setTariffLocal(filters.tariff_id), [filters.tariff_id]);

  const apiParams: SubscriptionListParams = useMemo(() => {
    const out: SubscriptionListParams = {
      page: filters.page,
      per_page: filters.page_size,
      sort: filters.sort,
    };
    if (filters.q) out.q = filters.q;
    if (filters.status) out.status = filters.status;
    if (filters.tariff_id) out.tariff = filters.tariff_id;
    if (filters.is_free_trial === '1') out.is_free_trial = true;
    else if (filters.is_free_trial === '0') out.is_free_trial = false;
    if (filters.expires_from) out.expires_from = filters.expires_from;
    if (filters.expires_to) out.expires_to = `${filters.expires_to}T23:59:59`;
    return out;
  }, [filters]);

  const query = useQuery({
    queryKey: ['subs', apiParams],
    queryFn: () => subscriptionsApi.list(apiParams),
    placeholderData: (prev) => prev,
  });

  const items = query.data?.items ?? [];
  const meta = query.data?.meta;

  const handleSort = (s: string) => {
    setFilter('sort', s, { resetPage: true });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Подписки</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Все ключи доступа: активные, истёкшие, деактивированные.
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-col items-start justify-between gap-2 sm:flex-row sm:items-center">
          <div>
            <CardTitle className="text-base">Список</CardTitle>
            <CardDescription>Server-side pagination, 50 на страницу</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={reset}>
            Сбросить
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-4">
            <div className="relative lg:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={qLocal}
                onChange={(e) => setQLocal(e.target.value)}
                placeholder="ID, ключ, юзер"
                className="pl-9"
              />
            </div>
            <Select
              value={filters.status}
              onChange={(e) => setFilter('status', e.target.value, { resetPage: true })}
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
            <Input
              value={tariffLocal}
              onChange={(e) => setTariffLocal(e.target.value)}
              placeholder="Код тарифа / id"
            />
            <Select
              value={filters.is_free_trial}
              onChange={(e) =>
                setFilter('is_free_trial', e.target.value, { resetPage: true })
              }
            >
              {TRIAL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
            <DatePicker
              value={filters.expires_from}
              onChange={(v) =>
                setFilter('expires_from', v, { resetPage: true })
              }
              placeholder="Истекает с"
            />
            <DatePicker
              value={filters.expires_to}
              onChange={(v) => setFilter('expires_to', v, { resetPage: true })}
              placeholder="Истекает по"
            />
          </div>

          {query.isLoading && !query.data ? (
            <Skeleton className="h-96 w-full" />
          ) : query.isError ? (
            <div className="space-y-2">
              <p className="text-sm text-destructive">Не удалось загрузить.</p>
              <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                Повторить
              </Button>
            </div>
          ) : items.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              Ничего не найдено.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      <SortHeader field="id" sort={filters.sort} onSort={handleSort}>
                        ID
                      </SortHeader>
                    </TableHead>
                    <TableHead>Юзер</TableHead>
                    <TableHead>Тариф</TableHead>
                    <TableHead className="text-right">Устр.</TableHead>
                    <TableHead className="text-right">Дней</TableHead>
                    <TableHead>Ключ</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead>
                      <SortHeader
                        field="expires_at"
                        sort={filters.sort}
                        onSort={handleSort}
                      >
                        Истекает
                      </SortHeader>
                    </TableHead>
                    <TableHead>
                      <SortHeader
                        field="created_at"
                        sort={filters.sort}
                        onSort={handleSort}
                      >
                        Создана
                      </SortHeader>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((s) => {
                    const expiringSoon = isExpiringSoon(s.expires_at, s.status);
                    return (
                      <TableRow
                        key={s.id}
                        className="cursor-pointer"
                        onClick={() => navigate(`/subscriptions/${s.id}`)}
                      >
                        <TableCell className="font-mono">#{s.id}</TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <Link
                            to={`/users/${s.user_id}`}
                            className="text-primary hover:underline"
                          >
                            {s.user_username
                              ? '@' + truncate(s.user_username, 18)
                              : `tg_id ${s.user_tg_id}`}
                          </Link>
                        </TableCell>
                        <TableCell>{s.tariff_name ?? s.tariff_code ?? '—'}</TableCell>
                        <TableCell className="text-right">{s.devices}</TableCell>
                        <TableCell className="text-right">{s.days ?? '—'}</TableCell>
                        <TableCell className="max-w-[220px] truncate font-mono text-xs">
                          {s.key_url ? truncate(s.key_url, 28) : '—'}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <Badge
                              variant={
                                s.status === 'active'
                                  ? 'success'
                                  : s.status === 'expired'
                                    ? 'warning'
                                    : s.status === 'deactivated'
                                      ? 'destructive'
                                      : 'muted'
                              }
                            >
                              {s.status}
                            </Badge>
                            {expiringSoon && (
                              <Badge
                                variant="warning"
                                title={`Истекает в течение ${EXPIRE_SOON_DAYS} дней`}
                              >
                                <Clock className="mr-1 h-3 w-3" />
                                soon
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(s.expires_at)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(s.created_at)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>

              {meta && (
                <Pagination
                  page={meta.page}
                  pages={meta.pages}
                  total={meta.total}
                  perPage={meta.per_page}
                  onPageChange={(p) => setFilter('page', p)}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
