import { useMemo } from 'react';
import { DayPicker } from 'react-day-picker';
import { CalendarIcon, X } from 'lucide-react';
import 'react-day-picker/style.css';

import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { formatDate } from '@/utils/format';

export interface DatePickerProps {
  /** ISO YYYY-MM-DD; ``''`` means unset. */
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

/** Convert a ``YYYY-MM-DD`` string to a Date in the local timezone. */
function fromIsoDate(value: string): Date | undefined {
  if (!value) return undefined;
  const [y, m, d] = value.split('-').map((p) => Number(p));
  if (!y || !m || !d) return undefined;
  const dt = new Date(y, m - 1, d);
  return Number.isNaN(dt.getTime()) ? undefined : dt;
}

function toIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function DatePicker({
  value,
  onChange,
  placeholder = 'Выбрать дату',
  className,
  disabled,
}: DatePickerProps) {
  const selected = useMemo(() => fromIsoDate(value), [value]);

  return (
    <div className={cn('inline-flex items-center gap-1', className)}>
      <Popover>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            className={cn(
              'h-10 w-full justify-start gap-2 px-3 text-left font-normal',
              !value && 'text-muted-foreground'
            )}
          >
            <CalendarIcon className="h-4 w-4 shrink-0" />
            {value ? formatDate(value) : placeholder}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0">
          <DayPicker
            mode="single"
            selected={selected}
            onSelect={(d) => {
              onChange(d ? toIsoDate(d) : '');
            }}
            weekStartsOn={1}
            className="p-3"
          />
        </PopoverContent>
      </Popover>
      {value && !disabled && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Очистить дату"
          onClick={() => onChange('')}
        >
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
