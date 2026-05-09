import { useEffect, useState, type ComponentType } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
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
  ChevronDown,
  Server,
  Wallet,
  Tag,
  Smartphone,
  Sparkles,
  Receipt,
} from 'lucide-react';

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/stores/uiStore';

interface NavLeaf {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

interface NavGroup {
  label: string;
  icon: ComponentType<{ className?: string }>;
  /** Path prefix used for "section is active" detection. */
  match: string;
  children: NavLeaf[];
}

type NavItem = NavLeaf | NavGroup;

function isGroup(item: NavItem): item is NavGroup {
  return 'children' in item;
}

const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/subscriptions', label: 'Подписки', icon: KeyRound },
  { to: '/payments', label: 'Платежи', icon: Receipt },
  { to: '/tariffs', label: 'Тарифы', icon: CreditCard },
  { to: '/promos', label: 'Промокоды', icon: Ticket },
  {
    label: 'NorthLine',
    icon: Server,
    match: '/northline',
    children: [
      { to: '/northline/profile', label: 'Профиль', icon: Wallet },
      { to: '/northline/prices', label: 'Прайс', icon: Tag },
      { to: '/northline/lte', label: 'LTE-пакеты', icon: Smartphone },
      { to: '/northline/branding', label: 'Брендинг', icon: Sparkles },
    ],
  },
  { to: '/broadcasts', label: 'Рассылки', icon: Megaphone },
  { to: '/texts', label: 'Тексты бота', icon: FileText },
  { to: '/logs/events', label: 'Логи событий', icon: ListChecks },
  { to: '/logs/tech', label: 'Технические логи', icon: Wrench },
  { to: '/settings/admin-keys', label: 'Настройки', icon: Settings },
];

interface NavBodyProps {
  collapsed: boolean;
  onNavigate?: () => void;
}

function NavBody({ collapsed, onNavigate }: NavBodyProps) {
  const location = useLocation();

  // Auto-expand any group whose path matches the current location so deep-link
  // navigation always reveals the active leaf.
  const initialOpen = () => {
    const out: Record<string, boolean> = {};
    for (const item of NAV_ITEMS) {
      if (isGroup(item)) {
        out[item.match] = location.pathname.startsWith(item.match);
      }
    }
    return out;
  };
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(initialOpen);

  useEffect(() => {
    setOpenGroups((prev) => {
      const next = { ...prev };
      for (const item of NAV_ITEMS) {
        if (isGroup(item) && location.pathname.startsWith(item.match)) {
          next[item.match] = true;
        }
      }
      return next;
    });
  }, [location.pathname]);

  return (
    <nav className="flex-1 space-y-1 overflow-y-auto p-2">
      {NAV_ITEMS.map((item) => {
        if (isGroup(item)) {
          const Icon = item.icon;
          const isActive = location.pathname.startsWith(item.match);
          const open = openGroups[item.match] ?? false;
          // Collapsed sidebar can't fit child rows — show just the parent
          // row, link it to the first child for click-through behaviour.
          if (collapsed) {
            const first = item.children[0];
            return (
              <NavLink
                key={item.match}
                to={first.to}
                onClick={onNavigate}
                className={cn(
                  'flex items-center justify-center rounded-md px-2 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                )}
                title={item.label}
              >
                <Icon className="h-4 w-4 shrink-0" />
              </NavLink>
            );
          }
          return (
            <div key={item.match}>
              <button
                type="button"
                onClick={() =>
                  setOpenGroups((prev) => ({
                    ...prev,
                    [item.match]: !prev[item.match],
                  }))
                }
                className={cn(
                  'flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="flex-1 truncate text-left">{item.label}</span>
                <ChevronDown
                  className={cn(
                    'h-4 w-4 shrink-0 transition-transform',
                    open ? 'rotate-0' : '-rotate-90'
                  )}
                />
              </button>
              {open && (
                <div className="mt-1 space-y-1 pl-4">
                  {item.children.map((child) => {
                    const ChildIcon = child.icon;
                    return (
                      <NavLink
                        key={child.to}
                        to={child.to}
                        onClick={onNavigate}
                        className={({ isActive: leafActive }) =>
                          cn(
                            'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                            leafActive
                              ? 'bg-accent text-accent-foreground'
                              : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                          )
                        }
                      >
                        <ChildIcon className="h-4 w-4 shrink-0" />
                        <span className="truncate">{child.label}</span>
                      </NavLink>
                    );
                  })}
                </div>
              )}
            </div>
          );
        }

        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
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
  );
}

function SidebarBrand({ collapsed }: { collapsed: boolean }) {
  return (
    <div
      className={cn(
        'flex h-16 items-center gap-2 border-b border-border px-4',
        collapsed && 'justify-center px-2'
      )}
    >
      <Shield className="h-6 w-6 shrink-0 text-primary" />
      {!collapsed && (
        <span className="text-lg font-semibold tracking-tight">PIX VPN</span>
      )}
    </div>
  );
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggle = useUIStore((s) => s.toggleSidebar);
  const mobileOpen = useUIStore((s) => s.mobileSidebarOpen);
  const setMobileOpen = useUIStore((s) => s.setMobileSidebarOpen);

  return (
    <>
      {/* Desktop / md+ — static rail */}
      <aside
        className={cn(
          'hidden shrink-0 border-r border-border bg-card md:flex md:flex-col transition-[width] duration-200 ease-in-out',
          collapsed ? 'w-16' : 'w-64'
        )}
      >
        <SidebarBrand collapsed={collapsed} />
        <NavBody collapsed={collapsed} />
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

      {/* Mobile drawer — opened from the Header hamburger */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent
          side="left"
          className="flex w-72 flex-col gap-0 p-0 sm:max-w-xs"
        >
          <SheetHeader className="px-0">
            <SidebarBrand collapsed={false} />
            <SheetTitle className="sr-only">Меню</SheetTitle>
          </SheetHeader>
          <NavBody collapsed={false} onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>
    </>
  );
}
