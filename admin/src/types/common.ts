export interface Paginated<T> {
  items: T[];
  total?: number;
  next_cursor?: string | null;
  before_id?: number | null;
}

export interface ApiError {
  detail?: string;
  message?: string;
}
