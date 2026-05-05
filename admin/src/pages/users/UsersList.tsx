import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';

import { usersApi } from '@/api/endpoints/users';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import { cn } from '@/lib/utils';
import { formatDateTime, formatNumber, formatRub } from '@/utils/format';
import type { UserListParams } from '@/types/api';

const PER_PAGE = 50;

interface FilterChipProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}
function FilterChip({ active, onClick, children }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
        active
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-background text-muted-foreground hover:text-foreground'
      )}
    >
      {children}
    </button>
  );
}

export default function UsersList() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [bannedOnly, setBannedOnly] = useState(false);
  const [withSub, setWithSub] = useState(false);
  const [balanceGtZero, setBalanceGtZero] = useState(false);
  const [sort, setSort] = useState<string | undefined>('created_at:desc');

  const debouncedSearch = useDebounce(search, 300);

  const params: UserListParams = useMemo(
    () => ({
      page,
      per_page: PER_PAGE,
      sort,
      q: debouncedSearch.trim() || undefined,
      banned: bannedOnly || undefined,
      with_subscription: withSub || undefined,
      balance_gt: balanceGtZero ? 0 : undefined,
    }),
    [page, sort, debouncedSearch, bannedOnly, withSub, balanceGtZero]
  );

  const query = useQuery({
    queryKey: ['users', params],
    queryFn: () => usersApi.list(params),
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
        <h1 className="text-3xl font-bold tracking-tight">Пользователи</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Поиск, фильтры и быстрый переход к карточке юзера.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Список</CardTitle>
          <CardDescription>Server-side pagination, 50 на страницу</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="relative max-w-md flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="tg_id, @username или имя"
                className="pl-9"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <FilterChip
                active={bannedOnly}
                onClick={() => {
                  setBannedOnly((v) => !v);
                  setPage(1);
                }}
              >
                Забаненные
              </FilterChip>
              <FilterChip
                active={withSub}
                onClick={() => {
                  setWithSub((v) => !v);
                  setPage(1);
                }}
              >
                С подпиской
              </FilterChip>
              <FilterChip
                active={balanceGtZero}
                onClick={() => {
                  setBalanceGtZero((v) => !v);
                  setPage(1);
                }}
              >
                Баланс &gt; 0
              </FilterChip>
            </div>
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
                      <SortHeader field="tg_id" sort={sort} onSort={handleSort}>
                        tg_id
                      </SortHeader>
                    </TableHead>
                    <TableHead>
                      <SortHeader field="username" sort={sort} onSort={handleSort}>
                        username
                      </SortHeader>
                    </TableHead>
                    <TableHead>Имя</TableHead>
                    <TableHead className="text-right">
                      <SortHeader
                        field="balance_kop"
                        sort={sort}
                        onSort={handleSort}
                      >
                        Баланс
                      </SortHeader>
                    </TableHead>
                    <TableHead className="text-right">Подписок</TableHead>
                    <TableHead>
                      <SortHeader
                        field="created_at"
                        sort={sort}
                        onSort={handleSort}
                      >
                        Создан
                      </SortHeader>
                    </TableHead>
                    <TableHead>Статус</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((u) => (
                    <TableRow
                      key={u.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/users/${u.id}`)}
                    >
                      <TableCell className="font-mono text-xs">{u.tg_id}</TableCell>
                      <TableCell>
                        {u.username ? '@' + u.username : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>{u.first_name ?? '—'}</TableCell>
                      <TableCell className="text-right font-medium">
                        {formatRub(u.balance_kop)}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatNumber(u.active_subscriptions_count)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(u.created_at)}
                      </TableCell>
                      <TableCell>
                        {u.is_banned ? (
                          <Badge variant="destructive">Бан</Badge>
                        ) : (
                          <Badge variant="success">Активен</Badge>
                        )}
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
