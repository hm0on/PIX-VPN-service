import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Copy, Loader2, Plus, Trash2 } from 'lucide-react';

import { getErrorMessage } from '@/api/client';
import {
  type AdminKey,
  authApi,
  type RotateResponse,
} from '@/api/endpoints/auth';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
import { useAuthStore } from '@/stores/authStore';
import { formatDateTime } from '@/utils/format';

type RevokeMode = 'grace' | 'now';

function deriveStatus(
  k: AdminKey,
  currentKid: number | null
): { label: string; variant: 'success' | 'warning' | 'muted' | 'destructive' } {
  const isCurrent = currentKid != null && k.id === currentKid;
  if (k.revoked_at) {
    const revoked = new Date(k.revoked_at).getTime();
    if (Number.isFinite(revoked) && revoked > Date.now()) {
      return { label: 'grace', variant: 'warning' };
    }
    return { label: 'отозван', variant: 'destructive' };
  }
  if (k.valid_until) {
    const until = new Date(k.valid_until).getTime();
    if (Number.isFinite(until) && until < Date.now()) {
      return { label: 'истёк', variant: 'muted' };
    }
  }
  return { label: isCurrent ? 'текущий' : 'активен', variant: 'success' };
}

export default function AdminKeys() {
  const queryClient = useQueryClient();
  const currentKid = useAuthStore((s) => s.keyId);
  const setAuth = useAuthStore((s) => s.login);

  const [rotateOpen, setRotateOpen] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [revokeMode, setRevokeMode] = useState<RevokeMode>('grace');
  const [newKey, setNewKey] = useState<RotateResponse | null>(null);

  const keysQuery = useQuery({
    queryKey: ['admin-keys'],
    queryFn: authApi.listKeys,
  });

  const rotateMutation = useMutation({
    mutationFn: () =>
      authApi.rotateKey({ new_label: newLabel.trim() || undefined }),
    onSuccess: (data) => {
      setNewKey(data);
      setRotateOpen(false);
      // After rotate the backend issues a new JWT bound to the new key — adopt it.
      setAuth({
        token: data.access_token,
        expiresAt: data.expires_at,
        label: data.new_label,
        keyId: data.new_key_id,
      });
      // If admin opted to revoke the previous key now (no grace), do it explicitly.
      if (revokeMode === 'now' && data.previous_key_id != null) {
        authApi.revokeKey(data.previous_key_id).catch((err) => {
          toast.error(`Не удалось отозвать старый ключ: ${getErrorMessage(err)}`);
        });
      }
      void queryClient.invalidateQueries({ queryKey: ['admin-keys'] });
      toast.success('Новый ключ сгенерирован');
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: number) => authApi.revokeKey(id),
    onSuccess: () => {
      toast.success('Ключ отозван');
      void queryClient.invalidateQueries({ queryKey: ['admin-keys'] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Скопировано в буфер обмена');
    } catch {
      toast.error('Не удалось скопировать');
    }
  };

  const keys = useMemo(() => keysQuery.data ?? [], [keysQuery.data]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Admin-ключи</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Просмотр, ротация и отзыв ключей доступа в админ-панель.
          </p>
        </div>
        <Button onClick={() => setRotateOpen(true)}>
          <Plus className="h-4 w-4" />
          Сгенерировать новый
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Список ключей</CardTitle>
          <CardDescription>
            При ротации старому ключу выдаётся grace-период 3 часа (если выбран).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {keysQuery.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : keysQuery.isError ? (
            <p className="text-sm text-destructive">
              Не удалось загрузить ключи: {getErrorMessage(keysQuery.error)}
            </p>
          ) : keys.length === 0 ? (
            <p className="text-sm text-muted-foreground">Ключей пока нет.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">ID</TableHead>
                  <TableHead>Название</TableHead>
                  <TableHead>Создан</TableHead>
                  <TableHead>Действителен до</TableHead>
                  <TableHead>Отозван</TableHead>
                  <TableHead>Статус</TableHead>
                  <TableHead className="w-24 text-right">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.map((k) => {
                  const status = deriveStatus(k, currentKid);
                  const isCurrent = currentKid != null && k.id === currentKid;
                  return (
                    <TableRow key={k.id}>
                      <TableCell className="font-mono text-xs">{k.id}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span>{k.label ?? '—'}</span>
                          {isCurrent && (
                            <Badge variant="default" className="text-[10px]">
                              текущий
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(k.created_at)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(k.valid_until)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(k.revoked_at)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="icon"
                          variant="ghost"
                          disabled={
                            isCurrent ||
                            Boolean(k.revoked_at) ||
                            revokeMutation.isPending
                          }
                          onClick={() => {
                            if (window.confirm('Отозвать ключ немедленно?')) {
                              revokeMutation.mutate(k.id);
                            }
                          }}
                          aria-label="Отозвать"
                          title={isCurrent ? 'Нельзя отозвать текущий ключ' : 'Отозвать'}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Rotation dialog */}
      <Dialog open={rotateOpen} onOpenChange={setRotateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Сгенерировать новый ключ</DialogTitle>
            <DialogDescription>
              Plaintext-ключ показывается только один раз — сохраните его сразу.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="key-label">Название (label)</Label>
              <Input
                id="key-label"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="напр. main-2026"
                disabled={rotateMutation.isPending}
                maxLength={64}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="revoke-mode">Старый ключ</Label>
              <Select
                id="revoke-mode"
                value={revokeMode}
                onChange={(e) => setRevokeMode(e.target.value as RevokeMode)}
                disabled={rotateMutation.isPending}
              >
                <option value="grace">Дать grace 3 часа</option>
                <option value="now">Отозвать немедленно</option>
              </Select>
              {revokeMode === 'now' && (
                <p className="text-xs text-destructive">
                  Старый ключ перестанет работать сразу.
                </p>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRotateOpen(false)}
              disabled={rotateMutation.isPending}
            >
              Отмена
            </Button>
            <Button
              onClick={() => rotateMutation.mutate()}
              disabled={rotateMutation.isPending}
            >
              {rotateMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Подтвердить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Show new key dialog */}
      <Dialog open={Boolean(newKey)} onOpenChange={(open) => !open && setNewKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый admin-ключ</DialogTitle>
            <DialogDescription>
              Скопируйте — больше не будет показан.
            </DialogDescription>
          </DialogHeader>

          {newKey && (
            <div className="space-y-3">
              <div className="break-all rounded-md border border-border bg-muted p-3 font-mono text-sm">
                {newKey.new_plaintext_key}
              </div>
              <Button
                variant="outline"
                onClick={() => handleCopy(newKey.new_plaintext_key)}
                className="w-full"
              >
                <Copy className="h-4 w-4" />
                Скопировать
              </Button>
              <p className="text-xs text-muted-foreground">
                Label: <span className="font-medium">{newKey.new_label}</span> · key_id:{' '}
                <span className="font-mono">{newKey.new_key_id}</span>
              </p>
            </div>
          )}

          <DialogFooter>
            <Button onClick={() => setNewKey(null)}>Готово</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
