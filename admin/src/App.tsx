import { Navigate, Route, Routes } from 'react-router-dom';

import { ProtectedRoute } from '@/components/ProtectedRoute';
import { AppShell } from '@/components/layout/AppShell';
import AdminKeys from '@/pages/settings/AdminKeys';
import Dashboard from '@/pages/Dashboard';
import Login from '@/pages/Login';
import NotFound from '@/pages/NotFound';
import UsersList from '@/pages/users/UsersList';
import UserDetail from '@/pages/users/UserDetail';
import SubsList from '@/pages/subscriptions/SubsList';
import SubDetail from '@/pages/subscriptions/SubDetail';
import Tariffs from '@/pages/tariffs/Tariffs';
import Promos from '@/pages/promos/Promos';
import BroadcastsList from '@/pages/broadcasts/BroadcastsList';
import BroadcastEditor from '@/pages/broadcasts/BroadcastEditor';
import BotTexts from '@/pages/texts/BotTexts';
import EventLogs from '@/pages/logs/EventLogs';
import TechLogs from '@/pages/logs/TechLogs';
import NorthlineProfile from '@/pages/northline/NorthlineProfile';
import NorthlinePrices from '@/pages/northline/NorthlinePrices';
import NorthlineLte from '@/pages/northline/NorthlineLte';
import NorthlineBranding from '@/pages/northline/NorthlineBranding';
import PaymentsList from '@/pages/payments/PaymentsList';
import { useAuthStore } from '@/stores/authStore';

function RootRedirect() {
  const isAuthenticated = useAuthStore((s) => Boolean(s.token));
  return <Navigate to={isAuthenticated ? '/dashboard' : '/login'} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />

        <Route path="/users" element={<UsersList />} />
        <Route path="/users/:id" element={<UserDetail />} />

        <Route path="/subscriptions" element={<SubsList />} />
        <Route path="/subscriptions/:id" element={<SubDetail />} />

        <Route path="/payments" element={<PaymentsList />} />

        <Route path="/northline" element={<Navigate to="/northline/profile" replace />} />
        <Route path="/northline/profile" element={<NorthlineProfile />} />
        <Route path="/northline/prices" element={<NorthlinePrices />} />
        <Route path="/northline/lte" element={<NorthlineLte />} />
        <Route path="/northline/branding" element={<NorthlineBranding />} />

        <Route path="/tariffs" element={<Tariffs />} />
        <Route path="/promos" element={<Promos />} />

        <Route path="/broadcasts" element={<BroadcastsList />} />
        <Route path="/broadcasts/:id/edit" element={<BroadcastEditor />} />

        <Route path="/texts" element={<BotTexts />} />

        <Route path="/logs/events" element={<EventLogs />} />
        <Route path="/logs/tech" element={<TechLogs />} />

        <Route path="/settings/admin-keys" element={<AdminKeys />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
