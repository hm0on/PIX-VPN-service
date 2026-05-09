import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';

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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';

// Use ``optional`` + manual ``''→null`` so the form's empty state maps to
// "clear this branding key" upstream rather than "leave unchanged".
const schema = z.object({
  custom_domain: z
    .string()
    .max(253, 'Слишком длинный домен')
    .optional(),
  service_name: z
    .string()
    .max(128, 'Слишком длинное имя')
    .optional(),
  service_description: z
    .string()
    .max(512, 'Слишком длинное описание')
    .optional(),
  support_url: z
    .string()
    .max(512, 'Слишком длинный URL')
    .optional()
    .refine(
      (v) => !v || /^https?:\/\//i.test(v),
      'URL должен начинаться с http:// или https://'
    ),
});

type FormValues = z.infer<typeof schema>;

export default function NorthlineBranding() {
  const queryClient = useQueryClient();

  const brandingQuery = useQuery({
    queryKey: ['northline', 'branding'],
    queryFn: northlineApi.branding,
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      custom_domain: '',
      service_name: '',
      service_description: '',
      support_url: '',
    },
  });

  // Pre-fill once data arrives. ``reset`` rather than ``setValue`` so the
  // dirty-state baseline matches what the server has, and a no-op submit is
  // visible-as-clean.
  useEffect(() => {
    if (!brandingQuery.data) return;
    const b = brandingQuery.data.branding ?? {};
    form.reset({
      custom_domain: typeof b.custom_domain === 'string' ? b.custom_domain : '',
      service_name: typeof b.service_name === 'string' ? b.service_name : '',
      service_description:
        typeof b.service_description === 'string' ? b.service_description : '',
      support_url: typeof b.support_url === 'string' ? b.support_url : '',
    });
  }, [brandingQuery.data, form]);

  const mutation = useMutation({
    mutationFn: (payload: FormValues) =>
      northlineApi.updateBranding({
        custom_domain: payload.custom_domain?.trim() || null,
        service_name: payload.service_name?.trim() || null,
        service_description: payload.service_description?.trim() || null,
        support_url: payload.support_url?.trim() || null,
      }),
    onSuccess: () => {
      toast.success('Брендинг сохранён');
      void queryClient.invalidateQueries({ queryKey: ['northline', 'branding'] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const onSubmit = form.handleSubmit((values) => mutation.mutate(values));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">NorthLine · Брендинг</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Глобальный брендинг для всех ключей реселлера. Каждая подписка может
          переопределить эти значения.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Параметры</CardTitle>
          <CardDescription>
            Пустое значение очищает поле upstream.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {brandingQuery.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : brandingQuery.isError ? (
            <div className="space-y-2">
              <p className="text-sm text-destructive">
                Не удалось загрузить: {getErrorMessage(brandingQuery.error)}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => brandingQuery.refetch()}
              >
                Повторить
              </Button>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="custom_domain">Custom domain</Label>
                <Input
                  id="custom_domain"
                  placeholder="vpn.example.com"
                  {...form.register('custom_domain')}
                />
                <p className="text-xs text-muted-foreground">
                  DNS A-record должен резолвиться в IP NorthLine.
                </p>
                {form.formState.errors.custom_domain && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.custom_domain.message}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="service_name">Service name</Label>
                <Input
                  id="service_name"
                  placeholder="PIX VPN"
                  {...form.register('service_name')}
                />
                {form.formState.errors.service_name && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.service_name.message}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="service_description">Service description</Label>
                <Textarea
                  id="service_description"
                  rows={3}
                  placeholder="Безопасный и быстрый VPN"
                  {...form.register('service_description')}
                />
                {form.formState.errors.service_description && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.service_description.message}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="support_url">Support URL</Label>
                <Input
                  id="support_url"
                  placeholder="https://t.me/your_support"
                  {...form.register('support_url')}
                />
                {form.formState.errors.support_url && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.support_url.message}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={mutation.isPending}
                  onClick={() => {
                    if (!brandingQuery.data) return;
                    const b = brandingQuery.data.branding ?? {};
                    form.reset({
                      custom_domain:
                        typeof b.custom_domain === 'string' ? b.custom_domain : '',
                      service_name:
                        typeof b.service_name === 'string' ? b.service_name : '',
                      service_description:
                        typeof b.service_description === 'string'
                          ? b.service_description
                          : '',
                      support_url:
                        typeof b.support_url === 'string' ? b.support_url : '',
                    });
                  }}
                >
                  Сбросить
                </Button>
                <Button
                  type="submit"
                  disabled={mutation.isPending || !form.formState.isDirty}
                >
                  {mutation.isPending && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  Сохранить
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
