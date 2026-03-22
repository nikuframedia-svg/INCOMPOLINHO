/**
 * ConsolePage.test.tsx — ConsolePage component tests.
 * Tests rendering of title, loading skeleton, and empty state.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to} data-testid="router-link">
      {children}
    </a>
  ),
}));

// Mock hook
vi.mock('@/features/console/hooks/useConsolePageData', () => ({
  useConsolePageData: vi.fn(() => ({
    dayData: null,
    loading: false,
    error: null,
    engine: null,
    allBlocks: [],
    lateDeliveries: null,
    panelOpen: false,
    downtimes: {},
    dailyUtils: [],
    sparklines: {},
    otd: null,
    clientMap: {},
    dayFeasibilityScore: 0,
    bannerVariant: 'info',
    bannerMessage: '',
    handleDaySelect: vi.fn(),
    handleBlockClick: vi.fn(),
    handleMachineClick: vi.fn(),
    handleNavigateToBlock: vi.fn(),
  })),
}));

// Mock child components
vi.mock('@/features/console/components/ActiveDecisions', () => ({
  ActiveDecisions: () => <div data-testid="active-decisions" />,
}));
vi.mock('@/features/console/components/AlertsFeed', () => ({
  AlertsFeed: () => <div data-testid="alerts-feed" />,
}));
vi.mock('@/features/console/components/AlertsPanel', () => ({
  AlertsPanel: () => <div data-testid="alerts-panel" />,
}));
vi.mock('@/features/console/components/AndonDrawer', () => ({
  AndonDrawer: () => <div data-testid="andon-drawer" />,
}));
vi.mock('@/features/console/components/D1Preparation', () => ({
  D1Preparation: () => <div data-testid="d1-prep" />,
}));
vi.mock('@/features/console/components/DayOrders', () => ({
  DayOrders: () => <div data-testid="day-orders" />,
}));
vi.mock('@/features/console/components/DaySelector', () => ({
  DaySelector: () => <div data-testid="day-selector" />,
}));
vi.mock('@/features/console/components/DeliveryRiskPanel', () => ({
  DeliveryRiskPanel: () => <div data-testid="delivery-risk" />,
}));
vi.mock('@/features/console/components/KPIGrid', () => ({
  KPIGrid: () => <div data-testid="kpi-grid" />,
}));
vi.mock('@/features/console/components/MachineStatusGrid', () => ({
  MachineStatusGrid: () => <div data-testid="machine-status" />,
}));
vi.mock('@/features/console/components/MachineTimeline', () => ({
  MachineTimeline: () => <div data-testid="machine-timeline" />,
}));
vi.mock('@/features/console/components/OperatorPanel', () => ({
  OperatorPanel: () => <div data-testid="operator-panel" />,
}));
vi.mock('@/features/console/components/TransparencyPanel', () => ({
  TransparencyPanel: () => <div data-testid="transparency-panel" />,
}));
vi.mock('@/features/console/components/WorkforceNeeds', () => ({
  WorkforceNeeds: () => <div data-testid="workforce-needs" />,
}));
vi.mock('@/components/Common/EmptyState', () => ({
  EmptyState: ({ title }: { title: string }) => <div data-testid="empty-state">{title}</div>,
}));
vi.mock('@/components/Common/FeatureErrorBoundary', () => ({
  FeatureErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/Common/SkeletonLoader', () => ({
  SkeletonCard: () => <div data-testid="skeleton-card" />,
  SkeletonTable: () => <div data-testid="skeleton-table" />,
}));
vi.mock('@/components/Common/StatusBanner', () => ({
  StatusBanner: () => <div data-testid="status-banner" />,
}));
vi.mock('@/theme/color-bridge', () => ({
  C: { t1: '#fff', t3: '#999', ac: '#00f' },
}));

import { useConsolePageData } from '@/features/console/hooks/useConsolePageData';
import { ConsolePage } from '@/features/console/pages/ConsolePage';

const mockHook = useConsolePageData as ReturnType<typeof vi.fn>;

describe('ConsolePage', () => {
  it('renders page title', () => {
    render(<ConsolePage />);
    expect(screen.getByText('Centro de Comando Diário')).toBeInTheDocument();
  });

  it('shows empty state when no data', () => {
    render(<ConsolePage />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('Ainda nao ha dados carregados')).toBeInTheDocument();
  });

  it('shows loading skeleton when loading', () => {
    mockHook.mockReturnValue({
      dayData: null,
      loading: true,
      error: null,
      engine: null,
      allBlocks: [],
      lateDeliveries: null,
      panelOpen: false,
      downtimes: {},
      dailyUtils: [],
      sparklines: {},
      otd: null,
      clientMap: {},
      dayFeasibilityScore: 0,
      bannerVariant: 'info',
      bannerMessage: '',
      handleDaySelect: vi.fn(),
      handleBlockClick: vi.fn(),
      handleMachineClick: vi.fn(),
      handleNavigateToBlock: vi.fn(),
    });

    render(<ConsolePage />);
    expect(screen.getByTestId('comando-diario-page')).toBeInTheDocument();
    expect(screen.getAllByTestId('skeleton-card').length).toBeGreaterThan(0);
  });
});
