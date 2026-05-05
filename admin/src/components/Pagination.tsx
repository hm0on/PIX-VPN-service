import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface PaginationProps {
  page: number;
  pages: number;
  total?: number;
  perPage?: number;
  onPageChange: (page: number) => void;
  className?: string;
}

export function Pagination({
  page,
  pages,
  total,
  perPage,
  onPageChange,
  className,
}: PaginationProps) {
  const canPrev = page > 1;
  const canNext = page < pages;

  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 text-sm text-muted-foreground',
        className
      )}
    >
      <div>
        {total != null && perPage
          ? `Всего: ${total.toLocaleString('ru-RU')} · ${perPage} на страницу`
          : `Страница ${page} из ${pages}`}
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          disabled={!canPrev}
          onClick={() => onPageChange(1)}
          aria-label="В начало"
        >
          <ChevronsLeft className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          disabled={!canPrev}
          onClick={() => onPageChange(page - 1)}
          aria-label="Назад"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="min-w-[5rem] text-center text-foreground">
          {page} / {Math.max(pages, 1)}
        </span>
        <Button
          variant="outline"
          size="icon"
          disabled={!canNext}
          onClick={() => onPageChange(page + 1)}
          aria-label="Вперёд"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          disabled={!canNext}
          onClick={() => onPageChange(pages)}
          aria-label="В конец"
        >
          <ChevronsRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
