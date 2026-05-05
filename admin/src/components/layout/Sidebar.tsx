import type { ComponentType } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  KeyRound,
  CreditCard,
  Ticket,
  Megaphone,
  FileText,
  ListChecks,
  Wrench,
  Settings,
  Shield,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { useUIStore } from '@/stores/uiStore';

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  emoji: string;
}

const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Дашборд', icon: LayoutDashboard, emoji: '📊' },
  { to: '/users', label: 'Пользователи', icon: Users, emoji: '👥' },
  { to: '/subscriptions', label: 'Подписки', icon: KeyRound, emoji: '🔑' },
  { to: '/tariffs', label: 'Тарифы', icon: CreditCard, emoji: '💳' },
  { to: '/promos', label: 'Промокоды', icon: Ticket, emoji: '🎟' },
  { to: '/broadcasts', label: 'Рассылки', icon: Megaphone, emoji: '📣' },
  { to: '/texts', label: 'Тексты бота', icon: FileText, emoji: '📝' },
  { to: '/logs/events', label: 'Логи событий', icon: ListChecks, emoji: '📋' },
  { to: '/logs/tech', label: 'Технические логи', icon: Wrench, emoji: '🔧' },
  { to: '/settings/admin-keys', label: 'Настройки', icon: Settings, emoji: '⚙️' },
];

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggle = useUIStore((s) => s.toggleSidebar);

  return (
    <aside
      className={cn(
        'hidden shrink-0 border-r border-border bg-card md:flex md:flex-col transition-[width] duration-200 ease-in-out',
        collapsed ? 'w-16' : 'w-64'
      )}
    >
      <div
        className={cn(
          'flex h-16 items-center gap-2 border-b border-border px-4',
          collapsed && 'justify-center px-2'
        )}
      >
        <Shield className="h-6 w-6 text-primary shrink-0" />
        {!collapsed && <span className="text-lg font-semibold">VPN PIX</span>}
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  collapsed && 'justify-center px-2',
                  isActive
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                )
              }
              title={collapsed ? item.label : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      <button
        type="button"
        onClick={toggle}
        className={cn(
          'flex h-10 items-center justify-center gap-2 border-t border-border text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground',
          collapsed ? 'px-2' : 'px-4'
        )}
        aria-label={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
      >
        {collapsed ? (
          <ChevronRight className="h-4 w-4" />
        ) : (
          <>
            <ChevronLeft className="h-4 w-4" />
            <span>Свернуть</span>
          </>
        )}
      </button>
    </aside>
  );
}
