import { Navigate, useLocation } from 'react-router-dom';
import { type ReactNode } from 'react';

import { useAuthStore } from '@/stores/authStore';

interface Props {
  children: ReactNode;
}

export function ProtectedRoute({ children }: Props) {
  const location = useLocation();
  const isAuthenticated = useAuthStore((s) => Boolean(s.token));

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
