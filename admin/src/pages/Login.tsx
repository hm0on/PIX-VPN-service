import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Loader2, Shield } from 'lucide-react';
import axios from 'axios';

import { authApi } from '@/api/endpoints/auth';
import { getErrorMessage } from '@/api/client';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useAuthStore } from '@/stores/authStore';

const schema = z.object({
  key: z
    .string()
    .min(8, 'Ключ должен быть не короче 8 символов')
    .max(512, 'Ключ слишком длинный'),
});

type FormValues = z.infer<typeof schema>;

export default function Login() {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.login);
  const [isLoading, setIsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { key: '' },
  });

  const onSubmit = async (values: FormValues) => {
    setIsLoading(true);
    try {
      const res = await authApi.login(values.key.trim());
      setAuth({
        token: res.access_token,
        expiresAt: res.expires_at,
        label: res.label ?? null,
        keyId: res.kid ?? res.key_id ?? null,
      });
      toast.success('Вход выполнен');
      navigate('/dashboard', { replace: true });
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 429) {
        toast.error('Слишком много попыток. Попробуйте позже.');
      } else {
        toast.error(getErrorMessage(err));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3">
          <div className="flex items-center gap-2">
            <Shield className="h-6 w-6 text-primary" />
            <span className="text-base font-medium text-muted-foreground">VPN PIX</span>
          </div>
          <CardTitle>Вход в админ-панель</CardTitle>
          <CardDescription>Введите admin-ключ для доступа.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="space-y-2">
              <Label htmlFor="key">Admin-ключ</Label>
              <Textarea
                id="key"
                rows={4}
                placeholder="Вставьте ключ из .env (ADMIN_INITIAL_KEY)"
                autoFocus
                autoComplete="off"
                spellCheck={false}
                disabled={isLoading}
                {...register('key')}
              />
              {errors.key && (
                <p className="text-sm text-destructive">{errors.key.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Войти
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
