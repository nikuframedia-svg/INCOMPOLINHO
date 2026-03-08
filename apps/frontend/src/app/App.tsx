import { ConfigProvider } from 'antd';
import ptPT from 'antd/locale/pt_PT';
import { lazy, Suspense } from 'react';
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import { ErrorBoundary } from '@/components/Common/ErrorBoundary';
import { SkeletonCard } from '@/components/Common/SkeletonLoader';
import { ToastContainer } from '@/components/Toast/Toast';
import { industrialTheme } from '@/theme/industrial-theme';
import { AppLayout } from './Layout';

/* ── Console ── */
const ConsolePage = lazy(() =>
  import('@/features/console/pages/ConsolePage').then((m) => ({ default: m.ConsolePage })),
);
const ConsoleDay = lazy(() =>
  import('@/features/console/pages/ConsoleDay').then((m) => ({ default: m.ConsoleDay })),
);

/* ── Plan ── */
const PlanPage = lazy(() =>
  import('@/features/plan/pages/PlanPage').then((m) => ({ default: m.PlanPage })),
);
const ReplanPage = lazy(() =>
  import('@/features/plan/pages/ReplanPage').then((m) => ({ default: m.ReplanPage })),
);
const WhatIfPage = lazy(() =>
  import('@/features/plan/pages/WhatIfPage').then((m) => ({ default: m.WhatIfPage })),
);
const DataPage = lazy(() =>
  import('@/features/plan/pages/DataPage').then((m) => ({ default: m.DataPage })),
);

/* ── MRP ── */
const MRPPage = lazy(() =>
  import('@/features/mrp/pages/MRPPage').then((m) => ({ default: m.MRPPage })),
);
const OrdersPage = lazy(() =>
  import('@/features/mrp/pages/OrdersPage').then((m) => ({ default: m.OrdersPage })),
);
const StockDetailPage = lazy(() =>
  import('@/features/mrp/pages/StockDetailPage').then((m) => ({ default: m.StockDetailPage })),
);
const CTPPage = lazy(() =>
  import('@/features/mrp/pages/CTPPage').then((m) => ({ default: m.CTPPage })),
);

/* ── Settings ── */
const SettingsPage = lazy(() =>
  import('@/features/settings/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);
const MachinesPage = lazy(() =>
  import('@/features/settings/pages/MachinesPage').then((m) => ({ default: m.MachinesPage })),
);
const ShiftsPage = lazy(() =>
  import('@/features/settings/pages/ShiftsPage').then((m) => ({ default: m.ShiftsPage })),
);
const SetupMatrixPage = lazy(() =>
  import('@/features/settings/pages/SetupMatrixPage').then((m) => ({ default: m.SetupMatrixPage })),
);
const OperatorsPage = lazy(() =>
  import('@/features/settings/pages/OperatorsPage').then((m) => ({ default: m.OperatorsPage })),
);
const CustomersPage = lazy(() =>
  import('@/features/settings/pages/CustomersPage').then((m) => ({ default: m.CustomersPage })),
);
const SchedulingConfigPage = lazy(() =>
  import('@/features/settings/pages/SchedulingConfigPage').then((m) => ({
    default: m.SchedulingConfigPage,
  })),
);

export function App() {
  return (
    <ConfigProvider theme={industrialTheme} locale={ptPT}>
      <Router>
        <AppLayout>
          <ErrorBoundary>
            <Suspense fallback={<SkeletonCard lines={5} />}>
              <Routes>
                {/* Redirect root to console */}
                <Route path="/" element={<Navigate to="/console" replace />} />

                {/* Console */}
                <Route path="/console" element={<ConsolePage />} />
                <Route path="/console/day/:date" element={<ConsoleDay />} />

                {/* Plan */}
                <Route path="/plan" element={<PlanPage />} />
                <Route path="/plan/replan" element={<ReplanPage />} />
                <Route path="/plan/whatif" element={<WhatIfPage />} />
                <Route path="/plan/data" element={<DataPage />} />

                {/* MRP */}
                <Route path="/mrp" element={<MRPPage />} />
                <Route path="/mrp/orders" element={<OrdersPage />} />
                <Route path="/mrp/stock/:sku" element={<StockDetailPage />} />
                <Route path="/mrp/ctp" element={<CTPPage />} />

                {/* Settings */}
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/settings/machines" element={<MachinesPage />} />
                <Route path="/settings/shifts" element={<ShiftsPage />} />
                <Route path="/settings/setup-matrix" element={<SetupMatrixPage />} />
                <Route path="/settings/operators" element={<OperatorsPage />} />
                <Route path="/settings/customers" element={<CustomersPage />} />
                <Route path="/settings/scheduling" element={<SchedulingConfigPage />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </AppLayout>
        <ToastContainer />
      </Router>
    </ConfigProvider>
  );
}
