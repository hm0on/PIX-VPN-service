import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Ban, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { getErrorMessage } from '@/api/client';
import { cancelBroadcast, listBroadcasts } from '@/api/endpoints/broadcasts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select } from '@/components/ui/select';
import { ServerPaginatedTable, type Column } from '@/components/data-table/ServerPaginatedTable';
import type { Broadcast, BroadcastStatus } from '@/types';

const statusVariant: Record<BroadcastStatus, 'muted' | 'info' | 'warning' | 'success' | 'destructive'> =
  {
    draft: 'muted',
    scheduled: 'info',
    sending: 'warning',
    done: 'success',
    cancelled: 'destructive',
  };

const statusLabel: Record<BroadcastStatus, string> = {
  draft: 'черновик',
  scheduled: 'запланирована',
  sending: 'идёт отправка',
  done: 'завершена',
  cancelled: 'отменена',
};

function formatDate(value: string | null): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU');
  } catch {
    return value;
  }
}

export default function BroadcastsList() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>('');

  const query = useQuery({
    queryKey: ['broadcasts', { statusFilter }],
    queryFn: () => listBroadcasts({ status: statusFilter || undefined }),
    refetchInterval: 30_000,
  });

  const cancelMut = useMutation({
    mutationFn: cancelBroadcast,
    onSuccess: () => {
      toast.success('Рассылка отменена');
      void qc.invalidateQueries({ queryKey: ['broadcasts'] });
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  });

  const columns: Column<Broadcast>[] = [
    { key: 'id', header: 'ID', cell: (b) => <span className="font-mono text-xs">#{b.id}</span> },
    {
      key: 'status',
      header: 'Статус',
      cell: (b) => (
        <Badge variant={statusVariant[b.status]}>{statusLabel[b.status]}</Badge>
      ),
    },
    { key: 'target', header: 'Цель', cell: (b) => (b.target === 'all' ? 'все' : 'подписчики') },
    {
      key: 'scheduled_at',
      header: 'Запуск',
      cell: (b) => formatDate(b.scheduled_at),
    },
    {
      key: 'progress',
      header: 'Прогресс',
      cell: (b) => `${b.sent} / ${b.recipients_total} (✗${b.failed})`,
    },
    { key: 'created_at', header: 'Создана', cell: (b) => formatDate(b.created_at) },
    {
      key: 'actions',
      header: '',
      cell: (b) => (
        <div className="flex justify-end gap-1">
          {(b.status === 'scheduled' || b.status === 'sending') && (
            <Button
              size="icon"
              variant="ghost"
              type="button"
              title="Отменить"
              onClick={(e) => {
                e.stopPropagation();
                if (window.confirm('Отменить рассылку?')) {
                  cancelMut.mutate(b.id);
                }
              }}
            >
              <Ban className="h-4 w-4" />
            </Button>
          )}
        </div>
      ),
      className: 'w-16 text-right',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Рассылки</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Сообщения с фото, кнопками и таргетингом по аудитории.
          </p>
        </div>
        <Button onClick={() => navigate('/broadcasts/new/edit')}>
          <Plus className="h-4 w-4" />
          Создать рассылку
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Фильтры</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <span className="text-sm">Статус:</span>
            <Select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-48"
            >
              <option value="">Все</option>
              <option value="draft">Черновик</option>
              <option value="scheduled">Запланированы</option>
              <option value="sending">Отправляются</option>
              <option value="done">Завершены</option>
              <option value="cancelled">Отменены</option>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Список</CardTitle>
        </CardHeader>
        <CardContent>
          <ServerPaginatedTable
            columns={columns}
            rows={query.data ?? []}
            isLoading={query.isLoading}
            rowKey={(b) => b.id}
            onRowClick={(b) => navigate(`/broadcasts/${b.id}/edit`)}
            emptyMessage="Рассылок нет"
          />
        </CardContent>
      </Card>
    </div>
  );
}
