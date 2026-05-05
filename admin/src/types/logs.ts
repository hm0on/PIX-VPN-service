export type LogLevel = 'info' | 'warning' | 'critical';
export type LogModule = 'bot' | 'backend' | 'worker';

export interface EventLog {
  id: number;
  created_at: string;
  level: LogLevel;
  event: string;
  module: LogModule | string;
  user_id: number | null;
  user_tg_id?: number | null;
  user_username?: string | null;
  message: string;
  context?: Record<string, unknown> | null;
}

export interface TechLog {
  id: number;
  created_at: string;
  trace_id: string;
  service: string;
  action: string;
  user_id: number | null;
  status: string | null;
  duration_ms: number | null;
  payload?: Record<string, unknown> | null;
  message?: string | null;
}

export interface EventLogsFilter {
  level?: LogLevel[];
  module?: LogModule | string;
  user?: string;
  event?: string;
  date_from?: string;
  date_to?: string;
  before_id?: number;
  limit?: number;
}

export interface TechLogsFilter {
  trace_id?: string;
  service?: string;
  action?: string;
  user_id?: number;
  date_from?: string;
  date_to?: string;
  before_id?: number;
  limit?: number;
}
