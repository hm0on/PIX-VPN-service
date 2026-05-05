import type { ReactNode } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';

import { cn } from '@/lib/utils';

export type SortDir = 'asc' | 'desc';

interface SortHeaderProps {
  field: string;
  sort: string | undefined;
  onSort: (sort: string) => void;
  children: ReactNode;
  className?: string;
}

function parseSort(sort: string | undefined): [string | null, SortDir] {
  if (!sort) return [null, 'asc'];
  const [field, dir] = sort.split(':');
  return [field ?? null, (dir as SortDir) === 'desc' ? 'desc' : 'asc'];
}

export function SortHeader({
  field,
  sort,
  onSort,
  children,
  className,
}: SortHeaderProps) {
  const [activeField, dir] = parseSort(sort);
  const isActive = activeField === field;

  const handleClick = () => {
    if (!isActive) onSort(`${field}:desc`);
    else if (dir === 'desc') onSort(`${field}:asc`);
    else onSort(`${field}:desc`);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        'inline-flex items-center gap-1 hover:text-foreground transition-colors',
        isActive && 'text-foreground',
        className
      )}
    >
      {children}
      {isActive ? (
        dir === 'desc' ? (
          <ArrowDown className="h-3 w-3" />
        ) : (
          <ArrowUp className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-40" />
      )}
    </button>
  );
}
