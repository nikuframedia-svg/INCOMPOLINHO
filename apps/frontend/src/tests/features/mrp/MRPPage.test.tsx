/**
 * MRPPage.test.tsx — MRP page component tests.
 * Tests rendering of header, loading state, and tab labels.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Mock hooks and stores
const mockScheduleData = vi.fn(() => ({
  engine: null,
  blocks: [],
  loading: false,
  error: null,
  metrics: null,
  lateDeliveries: null,
  mrp: null,
  mrpSkuView: null,
}));

vi.mock('@/hooks/useScheduleData', () => ({
  useScheduleData: (...args: unknown[]) => mockScheduleData(...args),
}));

vi.mock('@/stores/useUIStore', () => ({
  useUIStore: () => false,
  useUIActions: () => ({ setMrpRiskCount: vi.fn() }),
}));

// Mock child components
vi.mock('@/features/mrp/components/MRPPageHeader', () => ({
  MRPPageHeader: () => <div data-testid="mrp-page-header" />,
}));
vi.mock('@/features/mrp/components/MRPStatusSection', () => ({
  MRPStatusSection: () => <div data-testid="mrp-status" />,
}));
vi.mock('@/features/mrp/components/MRPTrustBanner', () => ({
  MRPTrustBanner: () => <div data-testid="mrp-trust" />,
}));
vi.mock('@/features/mrp/tabs/CTPTab', () => ({
  CTPTab: () => <div data-testid="ctp-tab" />,
}));
vi.mock('@/features/mrp/tabs/EncomendasTab', () => ({
  EncomendasTab: () => <div data-testid="encomendas-tab" />,
}));
vi.mock('@/features/mrp/tabs/MRPTableTab', () => ({
  SKUTableTab: () => <div data-testid="sku-table" />,
  ToolTableTab: () => <div data-testid="tool-table" />,
  MachineTableTab: () => <div data-testid="machine-table" />,
}));
vi.mock('@/features/mrp/tabs/StocksTab', () => ({
  StocksTab: () => <div data-testid="stocks-tab" />,
}));
vi.mock('@/components/Common/EmptyState', () => ({
  EmptyState: ({ title }: { title: string }) => <div data-testid="empty-state">{title}</div>,
}));
vi.mock('@/components/Common/FeatureErrorBoundary', () => ({
  FeatureErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/Common/SkeletonLoader', () => ({
  SkeletonTable: () => <div data-testid="skeleton-table" />,
}));
vi.mock('@/theme/color-bridge', () => ({
  C: { t1: '#fff' },
}));

import { MRPPage } from '@/features/mrp/pages/MRPPage';

describe('MRPPage', () => {
  it('renders page header text', () => {
    render(<MRPPage />);
    expect(screen.getByText(/MRP — Necessidades de Produção/)).toBeInTheDocument();
  });

  it('shows empty state when no data is loaded', () => {
    render(<MRPPage />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('Sem dados MRP')).toBeInTheDocument();
  });

  it('shows skeleton when loading', () => {
    mockScheduleData.mockReturnValue({
      engine: null,
      blocks: [],
      loading: true,
      error: null,
      metrics: null,
      lateDeliveries: null,
      mrp: null,
      mrpSkuView: null,
    });

    render(<MRPPage />);
    expect(screen.getByTestId('skeleton-table')).toBeInTheDocument();
  });

  it('shows tab labels when data is loaded', () => {
    const mockEngine = {
      machines: [{ id: 'PRM019', area: 'PG1' }],
      dates: ['2026-03-01'],
      dnames: ['Seg'],
    };
    const mockMrp = { records: [] };
    const mockSkuView = {
      skuRecords: [],
      summary: { skusWithStockout: 0 },
    };

    mockScheduleData.mockReturnValue({
      engine: mockEngine,
      blocks: [],
      loading: false,
      error: null,
      metrics: null,
      lateDeliveries: null,
      mrp: mockMrp,
      mrpSkuView: mockSkuView,
    });

    render(<MRPPage />);

    expect(screen.getByText('Stocks')).toBeInTheDocument();
    expect(screen.getByText('Tabela MRP')).toBeInTheDocument();
    expect(screen.getByText('Encomendas')).toBeInTheDocument();
    expect(screen.getByText('CTP')).toBeInTheDocument();
  });
});
