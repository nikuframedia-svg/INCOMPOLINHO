/**
 * KPICard.test.tsx — KPICard component tests.
 * Tests rendering of label, value, unit, subtitle, trend, and sparkline.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Mock echarts-for-react to avoid canvas rendering issues in tests
vi.mock('echarts-for-react/lib/core', () => ({
  default: ({ style }: { style: React.CSSProperties }) => (
    <div data-testid="echarts-sparkline" style={style} />
  ),
}));

vi.mock('echarts/core', () => ({ use: vi.fn(), default: { use: vi.fn() } }));
vi.mock('echarts/charts', () => ({ LineChart: {} }));
vi.mock('echarts/components', () => ({ GridComponent: {} }));
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }));

import { KPICard } from '@/components/Industrial/KPICard';

describe('KPICard', () => {
  it('renders label and value', () => {
    render(<KPICard label="OTD-D" value="97%" />);
    expect(screen.getByText('OTD-D')).toBeInTheDocument();
    expect(screen.getByText('97%')).toBeInTheDocument();
  });

  it('renders unit next to value', () => {
    render(<KPICard label="Produção" value="12,500" unit="pcs" />);
    expect(screen.getByText('pcs')).toBeInTheDocument();
  });

  it('renders subtitle with status color', () => {
    render(
      <KPICard
        label="OTD-D"
        value="97%"
        subtitle="Dentro do objectivo"
        statusColor="#22c55e"
      />,
    );
    const subtitle = screen.getByText('Dentro do objectivo');
    expect(subtitle).toBeInTheDocument();
    expect(subtitle).toHaveStyle({ color: '#22c55e' });
  });

  it('renders context line when provided', () => {
    render(
      <KPICard label="OTD-D" value="97%" contextLine="de 667 entregas, 649 a tempo" />,
    );
    expect(screen.getByText('de 667 entregas, 649 a tempo')).toBeInTheDocument();
  });

  it('renders trend indicator', () => {
    render(
      <KPICard
        label="Alertas"
        value="3"
        trend={{ direction: 'up', label: '2 overflow' }}
      />,
    );
    expect(screen.getByText(/2 overflow/)).toBeInTheDocument();
  });

  it('renders sparkline when data provided', () => {
    render(
      <KPICard label="Util" value="72%" sparkline={[60, 65, 70, 72]} />,
    );
    expect(screen.getByTestId('echarts-sparkline')).toBeInTheDocument();
  });

  it('does not render sparkline for empty array', () => {
    render(<KPICard label="Util" value="72%" sparkline={[]} />);
    expect(screen.queryByTestId('echarts-sparkline')).not.toBeInTheDocument();
  });

  it('does not render sparkline when not provided', () => {
    render(<KPICard label="Util" value="72%" />);
    expect(screen.queryByTestId('echarts-sparkline')).not.toBeInTheDocument();
  });

  it('renders status bar when statusColor is set', () => {
    const { container } = render(
      <KPICard label="OTD-D" value="97%" statusColor="#22c55e" />,
    );
    const bar = container.querySelector('.kpi-card__status-bar');
    expect(bar).toBeInTheDocument();
    expect(bar).toHaveStyle({ background: '#22c55e' });
  });
});
