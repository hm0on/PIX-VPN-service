import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import { listTech, traceChain } from '@/api/endpoints/logs';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { ServerPaginatedTable, type Column } from '@/components/data-table/ServerPaginatedTable';
import type { TechLog } from '@/types';

const PAGE_SIZE = 50;

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString('ru-RU');
  } catch {
    return value;
  }
}

export default function TechLogs() {
  const [traceId, setTraceId] = useState('');
  const [service, setService] = useState('');
  const [action, setAction] = useState('');
  const [userId, setUserId] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [cursorStack, setCursorStack] = useState<number[]>([]);
  const [beforeId, setBeforeId] = useState<number | undefined>(undefined);
  const [traceModal, setTraceModal] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      trace_id: traceId || undefined,
      service: service || undefined,
      action: action || undefined,
      user_id: userId ? Number(userId) : undefined,
      date_from: from || undefined,
      date_to: to || undefined,
      before_id: beforeId,
      limit: PAGE_SIZE,
    }),
    [traceId, service, action, userId, from, to, beforeId]
  );

  const query = useQuery({
    queryKey: ['tech-logs', params],
    queryFn: () => listTech(params),
    refetchInterval: 30_000,
  });

  const data = query.data ?? [];

  const columns: Column<TechLog>[] = [
    { key: 'created_at', header: 'Когда', cell: (l) => formatDate(l.created_at), className: 'whitespace-nowrap' },
    {
      key: 'trace_id',
      header: 'trace_id',
      cell: (l) => (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setTraceModal(l.trace_id);
          }}
          className="font-mono text-xs text-primary hover:underline"
        >
          {l.trace_id.slice(0, 8)}…
        </button>
      ),
      className: 'w-32',
    },
    { key: 'service', header: 'Сервис', cell: (l) => l.service, className: 'w-28' },
    { key: 'action', header: 'Действие', cell: (l) => l.action },
    {
      key: 'user',
      header: 'Юзер',
      cell: (l) => (l.user_id ? `#${l.user_id}` : '—'),
      className: 'w-20',
    },
    { key: 'status', header: 'Статус', cell: (l) => l.status ?? '—', className: 'w-24' },
    {
      key: 'duration',
      header: 'мс',
      cell: (l) => (l.duration_ms != null ? l.duration_ms : '—'),
      className: 'w-20',
    },
  ];

  const goNext = () => {
    if (data.length < PAGE_SIZE) return;
    const last = data[data.length - 1];
    setCursorStack((s) => [...s, last.id]);
    setBeforeId(last.id);
  };
  const goPrev = () => {
    if (cursorStack.length === 0) return;
    const next = cursorStack.slice(0, -1);
    setCursorStack(next);
    setBeforeId(next.length ? next[next.length - 1] : undefined);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Технические логи</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Трейсы вызовов сервисов, NorthLine, платёжных провайдеров и прочее.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Фильтры</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <Label>trace_id</Label>
              <Input
                value={traceId}
                onChange={(e) => setTraceId(e.target.value)}
                placeholder="abc123…"
              />
            </div>
            <div className="space-y-1">
              <Label>Сервис</Label>
              <Input
                value={service}
                onChange={(e) => setService(e.target.value)}
                placeholder="northline"
              />
            </div>
            <div className="space-y-1">
              <Label>Действие</Label>
              <Input
                value={action}
                onChange={(e) => setAction(e.target.value)}
                placeholder="create_key"
              />
            </div>
            <div className="space-y-1">
              <Label>user_id</Label>
              <Input
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                inputMode="numeric"
              />
            </div>
            <div className="space-y-1">
              <Label>С даты</Label>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>По дату</Label>
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>
          <div className="mt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setTraceId('');
                setService('');
                setAction('');
                setUserId('');
                setFrom('');
                setTo('');
                setBeforeId(undefined);
                setCursorStack([]);
              }}
            >
              Сбросить
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Записи</CardTitle>
        </CardHeader>
        <CardContent>
          {query.isError && (
            <p className="mb-2 text-sm text-destructive">{getErrorMessage(query.error)}</p>
          )}
          <ServerPaginatedTable
            columns={columns}
            rows={data}
            isLoading={query.isLoading}
            rowKey={(l) => l.id}
            emptyMessage="Записей нет"
            hasPrev={cursorStack.length > 0}
            hasNext={data.length >= PAGE_SIZE}
            onPrev={goPrev}
            onNext={goNext}
            pageInfo={`Записей: ${data.length}`}
          />
        </CardContent>
      </Card>

      <TraceChainDialog traceId={traceModal} onClose={() => setTraceModal(null)} />
    </div>
  );
}

interface TraceProps {
  traceId: string | null;
  onClose: () => void;
}

function TraceChainDialog({ traceId, onClose }: TraceProps) {
  const query = useQuery({
    queryKey: ['tech-trace', traceId],
    queryFn: () => traceChain(traceId!),
    enabled: !!traceId,
  });

  return (
    <Dialog open={!!traceId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Трейс {traceId}</DialogTitle>
          <DialogDescription>Полная цепочка событий по trace_id.</DialogDescription>
        </DialogHeader>

        {query.isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : query.isError ? (
          <p className="text-sm text-destructive">{getErrorMessage(query.error)}</p>
        ) : (
          <div className="max-h-[60vh] space-y-2 overflow-auto">
            {(query.data ?? []).map((l) => (
              <div key={l.id} className="rounded-md border border-border bg-card p-3">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{formatDate(l.created_at)}</span>
                  <span>
                    {l.service} → {l.action}
                  </span>
                </div>
                <div className="mt-1 text-xs">
                  Статус: <span className="font-mono">{l.status ?? '—'}</span>
                  {l.duration_ms != null && (
                    <>
                      {' '}
                      | <span className="font-mono">{l.duration_ms} ms</span>
                    </>
                  )}
                </div>
                {l.message && <div className="mt-1 text-xs">{l.message}</div>}
                {l.payload && (
                  <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted/40 p-2 text-[11px]">
                    {JSON.stringify(l.payload, null, 2)}
                  </pre>
                )}
              </div>
            ))}
            {(query.data ?? []).length === 0 && (
              <p className="py-6 text-center text-xs text-muted-foreground">
                Записей по этому trace_id нет
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
