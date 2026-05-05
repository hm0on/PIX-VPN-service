/**
 * Locale-aware formatting helpers used across the admin panel.
 * Money is stored in kopecks (kop) on the backend; UI shows roubles.
 */

const RUB_FORMATTER = new Intl.NumberFormat('ru-RU', {
  style: 'currency',
  currency: 'RUB',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

const NUMBER_FORMATTER = new Intl.NumberFormat('ru-RU');

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

const DATE_FORMATTER = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

export function formatRub(kopecks: number | null | undefined): string {
  if (kopecks == null) return '—';
  return RUB_FORMATTER.format(kopecks / 100);
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null) return '—';
  return NUMBER_FORMATTER.format(value);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return DATE_TIME_FORMATTER.format(d);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return DATE_FORMATTER.format(d);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '—';
  if (bytes === 0) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  const i = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(value < 10 && i > 0 ? 2 : 0)} ${units[i]}`;
}

export function truncate(value: string | null | undefined, max = 32): string {
  if (!value) return '—';
  if (value.length <= max) return value;
  return value.slice(0, max - 1) + '…';
}
