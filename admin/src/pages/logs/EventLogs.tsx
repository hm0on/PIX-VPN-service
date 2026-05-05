import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, Loader2 } from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import { eventsStream, listEvents } from '@/api/endpoints/logs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ServerPaginatedTable, type Column } from '@/components/data-table/ServerPaginatedTable';
import type { EventLog, LogLevel } from '@/types';

const LEVEL_VARIANT: Record<LogLevel, 'muted' | 'warning' | 'destructive'> = {
  info: 'muted',
  warning: 'warning',
  critical: 'destructive',
};

const PAGE_SIZE = 50;

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString('ru-RU');
  } catch {
    return value;
  }
}

export default function EventLogs() {
  const [levels, setLevels] = useState<LogLevel[]>([]);
  const [moduleFilter, setModuleFilter] = useState('');
  const [user, setUser] = useState('');
  const [eventQ, setEventQ] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [cursorStack, setCursorStack] = useState<number[]>([]);
  const [beforeId, setBeforeId] = useState<number | undefined>(undefined);
  const [live, setLive] = useState(false);
  const [liveItems, setLiveItems] = useState<EventLog[]>([]);
  const [expanded, setExpanded] = useState<EventLog | null>(null);

  const params = useMemo(
    () => ({
      level: levels.length ? levels : undefined,
      module: moduleFilter || undefined,
      user: user || undefined,
      event: eventQ || undefined,
      date_from: from || undefined,
      date_to: to || undefined,
      before_id: beforeId,
      limit: PAGE_SIZE,
    }),
    [levels, moduleFilter, user, eventQ, from, to, beforeId]
  );

  const query = useQuery({
    queryKey: ['event-logs', params],
    queryFn: () => listEvents(params),
    refetchInterval: live ? false : 30_000,
  });

  // SSE
  const esRef = useRef<EventSource | null>(null);
  useEffect(() => {
    if (!live) {
      esRef.current?.close();
      esRef.current = null;
      setLiveItems([]);
      return;
    }
    const es = eventsStream();
    if (!es) return;
    esRef.current = es;
    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as EventLog;
        setLiveItems((items) => [data, ...items].slice(0, 200));
      } catch {
        // ignore
      }
    };
    es.onerror = () => {
      // EventSource auto-reconnects; we just silently keep it
    };
    return () => {
      es.close();
      esRef.current = null;
    };
  }, [live]);

  const rows = live ? [...liveItems, ...(query.data ?? [])] : query.data ?? [];

  const columns: Column<EventLog>[] = [
    { key: 'created_at', header: 'Когда', cell: (l) => formatDate(l.created_at), className: 'whitespace-nowrap' },
    {
      key: 'level',
      header: 'Уровень',
      cell: (l) => (
        <Badge variant={LEVEL_VARIANT[l.level as LogLevel] ?? 'muted'}>{l.level}</Badge>
      ),
      className: 'w-24',
    },
    { key: 'event', header: 'Событие', cell: (l) => <span className="font-mono text-xs">{l.event}</span> },
    { key: 'module', header: 'Модуль', cell: (l) => l.module, className: 'w-24' },
    {
      key: 'user',
      header: 'Юзер',
      cell: (l) =>
        l.user_id ? (
          <a
            href={`/users/${l.user_id}`}
            className="text-primary hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {l.user_username ? `@${l.user_username}` : `#${l.user_id}`}
          </a>
        ) : (
          '—'
        ),
      className: 'w-32',
    },
    {
      key: 'message',
      header: 'Сообщение',
      cell: (l) => (
        <span className="line-clamp-2 break-words text-xs text-muted-foreground">
          {l.message}
        </span>
      ),
    },
  ];

  const data = query.data ?? [];

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

  const toggleLevel = (lvl: LogLevel) =>
    setLevels((curr) =>
      curr.includes(lvl) ? curr.filter((x) => x !== lvl) : [...curr, lvl]
    );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Логи событий</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            События приложения. Можно подключить live-стрим.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Activity className="h-4 w-4 text-muted-foreground" />
          <Label className="cursor-pointer">Live</Label>
          <Switch checked={live} onCheckedChange={setLive} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Фильтры</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <Label className="text-xs">Уровень</Label>
              <div className="flex gap-2">
                {(['info', 'warning', 'critical'] as LogLevel[]).map((lvl) => (
                  <Button
                    key={lvl}
                    type="button"
                    size="sm"
                    variant={levels.includes(lvl) ? 'default' : 'outline'}
                    onClick={() => toggleLevel(lvl)}
                  >
                    {lvl}
                  </Button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Модуль</Label>
              <Select
                value={moduleFilter}
                onChange={(e) => setModuleFilter(e.target.value)}
              >
                <option value="">Любой</option>
                <option value="bot">bot</option>
                <option value="backend">backend</option>
                <option value="worker">worker</option>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Событие</Label>
              <Input
                value={eventQ}
                onChange={(e) => setEventQ(e.target.value)}
                placeholder="user_registered"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Юзер (tg_id или @username)</Label>
              <Input value={user} onChange={(e) => setUser(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">С даты</Label>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">По дату</Label>
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">События</CardTitle>
        </CardHeader>
        <CardContent>
          {query.isError && (
            <p className="mb-2 text-sm text-destructive">{getErrorMessage(query.error)}</p>
          )}
          <ServerPaginatedTable
            columns={columns}
            rows={rows}
            isLoading={query.isLoading && !live}
            rowKey={(l) => l.id}
            onRowClick={(l) => setExpanded(l)}
            emptyMessage="Событий нет"
            hasPrev={cursorStack.length > 0}
            hasNext={data.length >= PAGE_SIZE}
            onPrev={goPrev}
            onNext={goNext}
            pageInfo={
              live ? (
                <span className="flex items-center gap-1 text-emerald-500">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Live: {liveItems.length}
                </span>
              ) : (
                `Записей: ${data.length}`
              )
            }
          />
        </CardContent>
      </Card>

      <EventDetailDialog log={expanded} onClose={() => setExpanded(null)} />
    </div>
  );
}

interface DetailProps {
  log: EventLog | null;
  onClose: () => void;
}

function EventDetailDialog({ log, onClose }: DetailProps) {
  return (
    <Dialog open={!!log} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{log?.event}</DialogTitle>
        </DialogHeader>
        {log && (
          <div className="space-y-2 text-sm">
            <div className="text-xs text-muted-foreground">{formatDate(log.created_at)}</div>
            <div>
              <Badge variant={LEVEL_VARIANT[log.level as LogLevel] ?? 'muted'}>
                {log.level}
              </Badge>{' '}
              <span className="text-xs text-muted-foreground">module: {log.module}</span>
            </div>
            {log.message && (
              <div className="rounded-md border border-border bg-muted/40 p-2 text-xs whitespace-pre-wrap break-words">
                {log.message}
              </div>
            )}
            {log.context && (
              <pre className="max-h-80 overflow-auto rounded-md border border-border bg-muted/40 p-2 text-xs">
                {JSON.stringify(log.context, null, 2)}
              </pre>
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
