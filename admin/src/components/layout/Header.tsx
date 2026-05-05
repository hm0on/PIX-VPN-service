import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { LogOut, RefreshCw, Sun, Moon, UserRound } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { useAuthStore } from '@/stores/authStore';
import { useUIStore } from '@/stores/uiStore';

export function Header() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const label = useAuthStore((s) => s.label);
  const logout = useAuthStore((s) => s.logout);
  const theme = useUIStore((s) => s.theme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const handleRefresh = async () => {
    await queryClient.invalidateQueries();
    toast.success('Данные обновлены');
  };

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-card px-6">
      <div className="text-sm text-muted-foreground">Админ-панель</div>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleRefresh}
          aria-label="Обновить"
          title="Обновить данные"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          aria-label="Переключить тему"
          title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
        >
          {theme === 'dark' ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>
        <Separator orientation="vertical" className="h-6" />
        <div className="flex items-center gap-2 text-sm">
          <UserRound className="h-4 w-4 text-muted-foreground" />
          <span className="text-foreground">{label ?? 'admin'}</span>
        </div>
        <Button variant="outline" size="sm" onClick={handleLogout}>
          <LogOut className="h-4 w-4" />
          Выход
        </Button>
      </div>
    </header>
  );
}
