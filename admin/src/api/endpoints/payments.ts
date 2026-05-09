import { api } from '@/api/client';
import type {
  AdminPaymentsListParams,
  AdminPaymentsPage,
} from '@/types/payments';

export const paymentsApi = {
  list: (params: AdminPaymentsListParams) =>
    api.get<AdminPaymentsPage>(
      '/admin/payments',
      params as Record<string, unknown>
    ),
};
