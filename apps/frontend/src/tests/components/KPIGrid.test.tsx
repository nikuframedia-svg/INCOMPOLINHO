/**
 * KPIGrid.test.tsx — KPIGrid component tests.
 * Tests that all 6 KPI cards render with correct labels and handle zero values.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Mock echarts
vi.mock('echarts-for-react/lib/core', () => ({
  default: () => <div data-testid="echarts-sparkline" />,
}));
vi.mock('echarts/core', () => ({ use: vi.fn(), default: { use: vi.fn() } }));
vi.mock('echarts/charts', () => ({ LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));

import { KPIGrid } from '@/features/console/components/KPIGrid';

const baseProps = {
  totalPcs: 25000,
  totalOps: 42,
  factoryUtil: 0.72,
  totalSetupMin: 180,
  violationCount: 2,
  infeasibleCount: 1,
  overflowCount: 0,
  operatorsByArea: { pg1: 6, pg2: 4, total: 10 },
  operatorCapacity: { pg1: 6, pg2: 4 },
  otd: 97.3,
};

describe('KPIGrid', () => {
  it('renders all 6 KPI cards', () => {
    render(<KPIGrid {...baseProps} />);
    const cards = screen.getAllByTestId('kpi-card');
    expect(cards.length).toBe(6);
  });

  it('renders expected KPI labels', () => {
    render(<KPIGrid {...baseProps} />);
    expect(screen.getByText('OTD-D')).toBeInTheDocument();
    expect(screen.getByText('Produção')).toBeInTheDocument();
    expect(screen.getByText('Operações')).toBeInTheDocument();
    expect(screen.getByText('Utilização')).toBeInTheDocument();
    expect(screen.getByText('Setup')).toBeInTheDocument();
    expect(screen.getByText('Alertas')).toBeInTheDocument();
  });

  it('renders production value formatted', () => {
    render(<KPIGrid {...baseProps} />);
    // toLocaleString formats 25000 — just check pcs unit is there
    expect(screen.getByText('pcs')).toBeInTheDocument();
  });

  it('renders OTD-D percentage', () => {
    render(<KPIGrid {...baseProps} />);
    expect(screen.getByText('97%')).toBeInTheDocument();
  });

  it('handles zero values gracefully', () => {
    render(
      <KPIGrid
        {...baseProps}
        totalPcs={0}
        totalOps={0}
        factoryUtil={0}
        totalSetupMin={0}
        violationCount={0}
        infeasibleCount={0}
        overflowCount={0}
        otd={100}
      />,
    );
    const cards = screen.getAllByTestId('kpi-card');
    expect(cards.length).toBe(6);
    expect(screen.getAllByText('0').length).toBeGreaterThan(0); // at least one zero value
  });

  it('shows late deliveries count when provided', () => {
    render(<KPIGrid {...baseProps} lateDeliveriesCount={3} />);
    expect(screen.getByText(/3 atrasos pendentes/)).toBeInTheDocument();
  });
});
