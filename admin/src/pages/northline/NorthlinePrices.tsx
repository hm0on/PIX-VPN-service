import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp } from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import { northlineApi } from '@/api/endpoints/northline';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
import { cn } from '@/lib/utils';

const RUB_FORMATTER = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

type SortKey = 'days' | 'devices' | 'total_price_rub';
type SortDir = 'asc' | 'desc';

export default function NorthlinePrices() {
  const [deviceFilter, setDeviceFilter] = useState<string>('');
  const [sortKey, setSortKey] = useState<SortKey>('days');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const pricesQuery = useQuery({
    queryKey: ['northline', 'prices'],
    queryFn: northlineApi.prices,
    refetchInterval: 60_000,
  });

  // Memoise so the empty-array fallback doesn't get a fresh identity on every
  // render — keeps downstream useMemo/useEffect deps stable.
  const rows = useMemo(
    () => pricesQuery.data?.price_matrix ?? [],
    [pricesQuery.data]
  );

  const deviceOptions = useMemo(() => {
    const uniq = Array.from(new Set(rows.map((r) => r.devices))).sort(
      (a, b) => a - b
    );
    return uniq;
  }, [rows]);

  const visible = useMemo(() => {
    const filtered = deviceFilter
      ? rows.filter((r) => r.devices === Number(deviceFilter))
      : rows;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [rows, deviceFilter, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const SortIcon = ({ active, dir }: { active: boolean; dir: SortDir }) => {
    if (!active) return null;
    return dir === 'asc' ? (
      <ArrowUp className="ml-1 inline h-3 w-3" />
    ) : (
      <ArrowDown className="ml-1 inline h-3 w-3" />
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">NorthLine · Прайс</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Матрица цен реселлера: длительность × количество устройств.
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="text-base">
              Матрица {pricesQuery.data ? `(${rows.length} строк)` : ''}
            </CardTitle>
            <CardDescription>
              {pricesQuery.data?.provider_key
                ? `Provider: ${pricesQuery.data.provider_key}`
                : '—'}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Устройств:</span>
            <Select
              value={deviceFilter}
              onChange={(e) => setDeviceFilter(e.target.value)}
              className="w-32"
            >
              <option value="">Все</option>
              {deviceOptions.map((n) => (
                <option key={n} value={String(n)}>
                  {n}
                </option>
              ))}
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {pricesQuery.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : pricesQuery.isError ? (
            <div className="space-y-2 py-6">
              <p className="text-sm text-destructive">
                Не удалось загрузить: {getErrorMessage(pricesQuery.error)}
              </p>
              <Button variant="outline" size="sm" onClick={() => pricesQuery.refetch()}>
                Повторить
              </Button>
            </div>
          ) : visible.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              Прайс пуст.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>
                    <button
                      type="button"
                      onClick={() => toggleSort('days')}
                      className={cn(
                        'inline-flex items-center text-xs font-medium uppercase tracking-wide',
                        sortKey === 'days' && 'text-foreground'
                      )}
                    >
                      Дней
                      <SortIcon active={sortKey === 'days'} dir={sortDir} />
                    </button>
                  </TableHead>
                  <TableHead>
                    <button
                      type="button"
                      onClick={() => toggleSort('devices')}
                      className={cn(
                        'inline-flex items-center text-xs font-medium uppercase tracking-wide',
                        sortKey === 'devices' && 'text-foreground'
                      )}
                    >
                      Устройств
                      <SortIcon active={sortKey === 'devices'} dir={sortDir} />
                    </button>
                  </TableHead>
                  <TableHead className="text-right">
                    <button
                      type="button"
                      onClick={() => toggleSort('total_price_rub')}
                      className={cn(
                        'inline-flex items-center text-xs font-medium uppercase tracking-wide',
                        sortKey === 'total_price_rub' && 'text-foreground'
                      )}
                    >
                      Цена, ₽
                      <SortIcon active={sortKey === 'total_price_rub'} dir={sortDir} />
                    </button>
                  </TableHead>
                  <TableHead>Override</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((row, idx) => (
                  <TableRow key={`${row.days}-${row.devices}-${idx}`}>
                    <TableCell>{row.days}</TableCell>
                    <TableCell>{row.devices}</TableCell>
                    <TableCell className="text-right font-medium">
                      {RUB_FORMATTER.format(row.total_price_rub)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {row.override_key ?? '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
