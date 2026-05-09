import { api } from '@/api/client';
import type {
  NorthlineBrandingResponse,
  NorthlineBrandingUpdateRequest,
  NorthlineLtePackages,
  NorthlinePriceQuote,
  NorthlinePriceQuoteParams,
  NorthlinePrices,
  NorthlineProfile,
} from '@/types/northline';

export const northlineApi = {
  profile: () => api.get<NorthlineProfile>('/admin/northline/profile'),
  prices: () => api.get<NorthlinePrices>('/admin/northline/prices'),
  ltePackages: () =>
    api.get<NorthlineLtePackages>('/admin/northline/lte-packages'),
  priceQuote: (params: NorthlinePriceQuoteParams) =>
    api.get<NorthlinePriceQuote>(
      '/admin/northline/price-quote',
      params as unknown as Record<string, unknown>
    ),
  branding: () => api.get<NorthlineBrandingResponse>('/admin/northline/branding'),
  updateBranding: (payload: NorthlineBrandingUpdateRequest) =>
    api.put<NorthlineBrandingResponse, NorthlineBrandingUpdateRequest>(
      '/admin/northline/branding',
      payload
    ),
};
