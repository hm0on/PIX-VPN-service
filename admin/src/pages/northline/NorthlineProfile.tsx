import { useQuery } from '@tanstack/react-query';
import type { LucideIcon } from 'lucide-react';
import { Activity, KeyRound, TrendingDown } from 'lucide-react';

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
import { formatNumber } from '@/utils/format';

const RUB_FORMATTER = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatRubFloat(value: number | null | undefined): string {
  if (value == null) return '—';
  return RUB_FORMATTER.format(value);
}

interface ChipProps {
  label: string;
  value: string;
  icon: LucideIcon;
}

function Chip({ label, value, icon: Icon }: ChipProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <Icon className="h-5 w-5 text-muted-foreground" />
      <div className="flex flex-col">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span className="text-base font-semibold text-foreground">{value}</span>
      </div>
    </div>
  );
}

export default function NorthlineProfile() {
  const profileQuery = useQuery({
    queryKey: ['northline', 'profile'],
    queryFn: northlineApi.profile,
    refetchInterval: 30_000,
  });

  const profile = profileQuery.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">NorthLine · Профиль</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Состояние реселлерского счёта upstream-провайдера. Автообновление
          каждые 30 секунд.
        </p>
      </div>

      {profileQuery.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : profileQuery.isError || !profile ? (
        <Card>
          <CardContent className="space-y-3 py-6">
            <p className="text-sm text-destructive">
              Не удалось загрузить профиль: {getErrorMessage(profileQuery.error)}
            </p>
            <Button variant="outline" size="sm" onClick={() => profileQuery.refetch()}>
              Повторить
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden border-primary/20 bg-gradient-to-br from-primary/10 via-card to-card">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="space-y-1">
                <CardDescription className="text-xs uppercase tracking-widest">
                  Баланс реселлера
                </CardDescription>
                <CardTitle className="text-5xl font-bold tracking-tight">
                  {formatRubFloat(profile.balance_rub)}
                </CardTitle>
                <p className="pt-1 text-sm text-muted-foreground">
                  Ключ:{' '}
                  <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                    {profile.provider_key}
                  </code>
                  {profile.label ? ` · ${profile.label}` : ''}
                </p>
              </div>
              <Badge variant={profile.active ? 'success' : 'destructive'}>
                {profile.active ? 'active' : 'inactive'}
              </Badge>
            </CardHeader>
          </Card>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Chip
              label="Выпущено всего"
              value={formatNumber(profile.issued_total)}
              icon={KeyRound}
            />
            <Chip
              label="Активно сейчас"
              value={formatNumber(profile.active_total)}
              icon={Activity}
            />
            <Chip
              label="Потрачено, ₽"
              value={formatRubFloat(profile.spent_rub)}
              icon={TrendingDown}
            />
          </div>
        </>
      )}
    </div>
  );
}
