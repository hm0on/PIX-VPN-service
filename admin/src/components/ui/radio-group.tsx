import * as React from 'react';

import { cn } from '@/lib/utils';

interface RadioContextValue {
  name: string;
  value: string;
  onChange: (value: string) => void;
}

const RadioContext = React.createContext<RadioContextValue | null>(null);

export interface RadioGroupProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  name: string;
  value: string;
  onValueChange: (value: string) => void;
}

export function RadioGroup({
  name,
  value,
  onValueChange,
  className,
  children,
  ...rest
}: RadioGroupProps) {
  return (
    <RadioContext.Provider value={{ name, value, onChange: onValueChange }}>
      <div role="radiogroup" className={cn('flex flex-col gap-2', className)} {...rest}>
        {children}
      </div>
    </RadioContext.Provider>
  );
}

export interface RadioItemProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  value: string;
  disabled?: boolean;
}

export function RadioItem({ value, disabled, className, children, ...rest }: RadioItemProps) {
  const ctx = React.useContext(RadioContext);
  if (!ctx) throw new Error('RadioItem must be used inside RadioGroup');
  const checked = ctx.value === value;
  return (
    <label
      className={cn(
        'flex cursor-pointer items-center gap-2 text-sm',
        disabled && 'cursor-not-allowed opacity-50',
        className
      )}
      {...rest}
    >
      <input
        type="radio"
        name={ctx.name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={() => ctx.onChange(value)}
        className="h-4 w-4 accent-primary"
      />
      <span>{children}</span>
    </label>
  );
}
