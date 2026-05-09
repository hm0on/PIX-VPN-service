import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Download, Search } from 'lucide-react';

import { paymentsApi } from '@/api/endpoints/payments';
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
import { useDebounce } from '@/hooks/use-debounce';
import { useUrlFilters } from '@/hooks/useUrlFilters';
import { formatDateTime, formatRub, truncate } from '@/utils/format';
import type {
  AdminPaymentListItem,
  AdminPaymentsListParams,
} from '@/types/payments';

const STATUS_OPTIONS = [
  { value: '', label: 'Все статусы' },
  { value: 'pending', label: 'Pending' },
  { value: 'paid', label: 'Paid' },
  { value: 'failed', label: 'Failed' },
  { value: 'expired', label: 'Expired' },
  { value: 'refunded', label: 'Refunded' },
];

const PROVIDER_OPTIONS = [
  { value: '', label: 'Все провайдеры' },
  { value: 'platega_sbp', label: 'Platega SBP' },
  { value: 'platega_crypto', label: 'Platega Crypto' },
  { value: 'cryptobot', label: 'CryptoBot' },
  { value: 'balance', label: 'Balance' },
];

const PURPOSE_OPTIONS = [
  { value: '', label: 'Все цели' },
  { value: 'subscription', label: 'Подписка' },
  { value: 'topup', label: 'Пополнение' },
];

interface PaymentsFilters {
  status: string;
  provider: string;
  purpose: string;
  user_id: string;
  q: string;
  created_from: string;
  created_to: string;
  page: number;
  page_size: number;
  [key: string]: string | number | boolean | undefined;
}

const DEFAULTS: PaymentsFilters = {
  status: '',
  provider: '',
  purpose: '',
  user_id: '',
  q: '',
  created_from: '',
  created_to: '',
  page: 1,
  page_size: 50,
};

function badgeForStatus(status: string) {
  if (status === 'paid') return 'success' as const;
  if (status === 'pending') return 'info' as const;
  if (status === 'failed' || status === 'expired') return 'destructive' as const;
  if (status === 'refunded') return 'warning' as const;
  return 'muted' as const;
}

/** Escape one CSV cell. Doubles quotes per RFC 4180. */
function csvCell(value: unknown): string {
  if (value == null) return '';
  const s = String(value);
  if (/[",\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function buildCsv(rows: AdminPaymentListItem[]): string {
  const header = [
    'id',
    'created_at',
    'paid_at',
    'user_id',
    'user_tg_id',
    'user_username',
    'subscription_id',
    'purpose',
    'provider',
    'external_id',
    'amount_kop',
    'currency',
    'status',
  ];
  const lines = [header.join(',')];
  for (const r of rows) {
    lines.push(
      [
        r.id,
        r.created_at,
        r.paid_at ?? '',
        r.user_id,
        r.user_tg_id ?? '',
        r.user_username ?? '',
        r.subscription_id ?? '',
        r.purpose,
        r.provider,
        r.external_id ?? '',
        r.amount_kop,
        r.currency,
        r.status,
      ]
        .map(csvCell)
        .join(',')
    );
  }
  return lines.join('\n');
}

export default function PaymentsList() {
  const { filters, setFilter, reset } = useUrlFilters({
    defaults: DEFAULTS,
  });

  // Debounce text-y inputs locally so they don't punish the URL-bar with a
  // history entry per keystroke.
  const [qLocal, setQLocal] = useState(filters.q);
  const [userLocal, setUserLocal] = useState(filters.user_id);
  const debouncedQ = useDebounce(qLocal, 300);
  const debouncedUser = useDebounce(userLocal, 300);

  useEffect(() => {
    if (debouncedQ !== filters.q) setFilter('q', debouncedQ, { resetPage: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);
  useEffect(() => {
    if (debouncedUser !== filters.user_id)
      setFilter('user_id', debouncedUser, { resetPage: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedUser]);

  // If the URL changes from elsewhere (e.g. reset), keep local mirrors in sync.
  useEffect(() => {
    setQLocal(filters.q);
  }, [filters.q]);
  useEffect(() => {
    setUserLocal(filters.user_id);
  }, [filters.user_id]);

  const apiParams: AdminPaymentsListParams = useMemo(() => {
    const out: AdminPaymentsListParams = {
      page: filters.page,
      page_size: filters.page_size,
    };
    if (filters.status) out.status = filters.status;
    if (filters.provider) out.provider = filters.provider;
    if (filters.purpose) out.purpose = filters.purpose;
    if (filters.q) out.q = filters.q;
    if (filters.user_id) {
      const n = Number(filters.user_id);
      if (Number.isFinite(n) && n > 0) out.user_id = n;
    }
    if (filters.created_from) out.created_from = filters.created_from;
    if (filters.created_to) {
      // ``created_to`` from a date-picker is a day; widen to end-of-day so the
      // range is inclusive of payments made later that calendar day.
      out.created_to = `${filters.created_to}T23:59:59`;
    }
    return out;
  }, [filters]);

  const query = useQuery({
    queryKey: ['payments', apiParams],
    queryFn: () => paymentsApi.list(apiParams),
    placeholderData: (prev) => prev,
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const total = query.data?.total ?? 0;
  const pageSize = query.data?.page_size ?? filters.page_size;
  const pages = Math.max(1, Math.ceil(total / pageSize));

  // Page-level pivot: sum of paid items in the visible page. Documented in
  // the spec as "ok for MVP" — full-period pivot would need a backend agg.
  const paidSum = useMemo(
    () =>
      items
        .filter((p) => p.status === 'paid')
        .reduce((acc, p) => acc + (p.amount_kop ?? 0), 0),
    [items]
  );

  const handleExportCsv = () => {
    const csv = buildCsv(items);
    // Prepend a UTF-8 BOM (U+FEFF) so Excel detects the encoding when
    // opening the file with Cyrillic content.
    const blob = new Blob(['\ufeff', csv], {
      type: 'text/csv;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `payments-page-${filters.page}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Платежи</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Глобальный листинг по всем пользователям. Фильтры синхронизированы с
          URL.
        </p>
      </div>

      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <CardTitle className="text-base">Список</CardTitle>
              <CardDescription>
                Всего: {total.toLocaleString('ru-RU')} · Paid на странице:{' '}
                <span className="font-medium text-foreground">
                  {formatRub(paidSum)}
                </span>
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleExportCsv}
                disabled={items.length === 0}
              >
                <Download className="h-4 w-4" />
                Export CSV
              </Button>
              <Button variant="ghost" size="sm" onClick={reset}>
                Сбросить
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-4">
            <div className="relative lg:col-span-2">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={qLocal}
                onChange={(e) => setQLocal(e.target.value)}
                placeholder="ID, external id, username, имя"
                className="pl-9"
              />
            </div>
            <Input
              value={userLocal}
              onChange={(e) => setUserLocal(e.target.value)}
              placeholder="user_id"
              type="number"
              min={1}
            />
            <Select
              value={filters.status}
              onChange={(e) => setFilter('status', e.target.value, { resetPage: true })}
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
            <Select
              value={filters.provider}
              onChange={(e) =>
                setFilter('provider', e.target.value, { resetPage: true })
              }
            >
              {PROVIDER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
            <Select
              value={filters.purpose}
              onChange={(e) =>
                setFilter('purpose', e.target.value, { resetPage: true })
              }
            >
              {PURPOSE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
            <DatePicker
              value={filters.created_from}
              onChange={(v) =>
                setFilter('created_from', v, { resetPage: true })
              }
              placeholder="С даты"
            />
            <DatePicker
              value={filters.created_to}
              onChange={(v) => setFilter('created_to', v, { resetPage: true })}
              placeholder="По дату"
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
              Платежи не найдены под текущие фильтры.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Создан</TableHead>
                    <TableHead>Юзер</TableHead>
                    <TableHead>Цель</TableHead>
                    <TableHead>Провайдер</TableHead>
                    <TableHead>External</TableHead>
                    <TableHead className="text-right">Сумма</TableHead>
                    <TableHead>Статус</TableHead>
                    <TableHead>Оплачен</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-mono text-xs">#{p.id}</TableCell>
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
                            : `tg_id ${p.user_tg_id ?? '—'}`}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{p.purpose}</Badge>
                      </TableCell>
                      <TableCell>{p.provider}</TableCell>
                      <TableCell className="max-w-[180px] truncate font-mono text-xs">
                        {p.external_id ?? '—'}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatRub(p.amount_kop)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badgeForStatus(p.status)}>
                          {p.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(p.paid_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <Pagination
                page={filters.page}
                pages={pages}
                total={total}
                perPage={pageSize}
                onPageChange={(p) => setFilter('page', p)}
              />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
