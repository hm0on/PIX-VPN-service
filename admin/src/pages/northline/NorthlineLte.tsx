import { useQuery } from '@tanstack/react-query';
import { Smartphone } from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import { northlineApi } from '@/api/endpoints/northline';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const RUB_FORMATTER = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * The current default LTE bundle shipped with our subscriptions. Highlighted
 * so ops can spot the row at a glance.
 */
const DEFAULT_LTE_GB = 35;

export default function NorthlineLte() {
  const ltequery = useQuery({
    queryKey: ['northline', 'lte'],
    queryFn: northlineApi.ltePackages,
    refetchInterval: 60_000,
  });

  const packages = ltequery.data?.packages ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">NorthLine · LTE-пакеты</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Доступные мобильные надбавки. Подсвечен текущий дефолт{' '}
          {DEFAULT_LTE_GB} ГБ.
        </p>
      </div>

      {ltequery.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : ltequery.isError ? (
        <Card>
          <CardContent className="space-y-2 py-6">
            <p className="text-sm text-destructive">
              Не удалось загрузить: {getErrorMessage(ltequery.error)}
            </p>
            <Button variant="outline" size="sm" onClick={() => ltequery.refetch()}>
              Повторить
            </Button>
          </CardContent>
        </Card>
      ) : packages.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            Пакетов не найдено.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {packages.map((p) => {
            const isDefault = p.gb === DEFAULT_LTE_GB;
            return (
              <Card
                key={`${p.gb}-${p.price_rub}`}
                className={cn(
                  'transition-shadow',
                  isDefault &&
                    'border-primary/60 ring-2 ring-primary/30 shadow-md'
                )}
              >
                <CardHeader className="space-y-1">
                  <div className="flex items-center justify-between">
                    <CardDescription className="flex items-center gap-2 text-xs uppercase tracking-wide">
                      <Smartphone className="h-3.5 w-3.5" />
                      LTE-пакет
                    </CardDescription>
                    {isDefault && (
                      <Badge variant="default">по умолчанию</Badge>
                    )}
                  </div>
                  <CardTitle className="text-3xl">
                    {p.gb}
                    <span className="ml-1 text-base font-medium text-muted-foreground">
                      ГБ
                    </span>
                  </CardTitle>
                  {p.label && (
                    <p className="text-xs text-muted-foreground">{p.label}</p>
                  )}
                </CardHeader>
                <CardContent className="space-y-1">
                  <div className="text-xl font-semibold">
                    {RUB_FORMATTER.format(p.price_rub)}
                  </div>
                  {p.rate != null && (
                    <p className="text-xs text-muted-foreground">
                      {RUB_FORMATTER.format(p.rate)} / ГБ
                    </p>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
