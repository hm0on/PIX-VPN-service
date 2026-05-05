import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';

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
import { Pagination } from '@/components/Pagination';
import { SortHeader } from '@/components/SortHeader';
import { useDebounce } from '@/hooks/use-debounce';
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

export default function SubsList() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [tariff, setTariff] = useState('');
  const [trialOnly, setTrialOnly] = useState(false);
  const [sort, setSort] = useState<string | undefined>('created_at:desc');

  const debouncedSearch = useDebounce(search, 300);
  const debouncedTariff = useDebounce(tariff, 300);

  const params: SubscriptionListParams = useMemo(
    () => ({
      page,
      per_page: PER_PAGE,
      sort,
      q: debouncedSearch.trim() || undefined,
      status: status || undefined,
      tariff: debouncedTariff.trim() || undefined,
      is_free_trial: trialOnly || undefined,
    }),
    [page, sort, debouncedSearch, status, debouncedTariff, trialOnly]
  );

  const query = useQuery({
    queryKey: ['subs', params],
    queryFn: () => subscriptionsApi.list(params),
    placeholderData: (prev) => prev,
  });

  const items = query.data?.items ?? [];
  const meta = query.data?.meta;

  const handleSort = (s: string) => {
    setSort(s);
    setPage(1);
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
        <CardHeader>
          <CardTitle className="text-base">Список</CardTitle>
          <CardDescription>Server-side pagination, 50 на страницу</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-[1fr_180px_180px_auto]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="ID, ключ, юзер"
                className="pl-9"
              />
            </div>
            <Select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
            <Input
              value={tariff}
              onChange={(e) => {
                setTariff(e.target.value);
                setPage(1);
              }}
              placeholder="Код тарифа"
            />
            <label className="inline-flex items-center gap-2 text-sm whitespace-nowrap">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={trialOnly}
                onChange={(e) => {
                  setTrialOnly(e.target.checked);
                  setPage(1);
                }}
              />
              Только триал
            </label>
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
                      <SortHeader field="id" sort={sort} onSort={handleSort}>
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
                        sort={sort}
                        onSort={handleSort}
                      >
                        Истекает
                      </SortHeader>
                    </TableHead>
                    <TableHead>
                      <SortHeader
                        field="created_at"
                        sort={sort}
                        onSort={handleSort}
                      >
                        Создана
                      </SortHeader>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((s) => (
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

              {meta && (
                <Pagination
                  page={meta.page}
                  pages={meta.pages}
                  total={meta.total}
                  perPage={meta.per_page}
                  onPageChange={setPage}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
