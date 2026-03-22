/**
 * GanttChart.test.tsx — GanttView component tests.
 * Tests rendering with empty and populated data.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mockInteractionState = {
  hov: null,
  selDay: 0,
  selM: null,
  zoom: 1,
  selOp: null,
  selBlock: null,
  dayB: [],
  dayBlkN: 0,
  activeM: [] as Array<{ id: string; area: string }>,
  wdi: [0],
  ppm: 1,
  totalW: 1000,
  violationsByDay: {},
};

const mockInteractionActions = {
  setHov: vi.fn(),
  setSelDay: vi.fn(),
  setSelM: vi.fn(),
  setZoom: vi.fn(),
  setSelOp: vi.fn(),
};

// Mock hooks
vi.mock('@/features/scheduling/hooks/useGanttDragDrop', () => ({
  useGanttDragDrop: () => ({
    drag: { isDragging: false, block: null, offsetX: 0, offsetY: 0, ghostX: 0, ghostY: 0 },
    proposedMove: null,
    startDrag: vi.fn(),
    endDrag: vi.fn(),
    clearProposal: vi.fn(),
  }),
}));

vi.mock('@/features/scheduling/hooks/useGanttInteraction', () => ({
  useGanttInteraction: () => ({
    state: mockInteractionState,
    actions: mockInteractionActions,
  }),
}));

// Mock sub-components
vi.mock('@/features/scheduling/components/GanttChart/GanttControls', () => ({
  GanttControls: () => <div data-testid="gantt-controls" />,
}));
vi.mock('@/features/scheduling/components/GanttChart/GanttLegend', () => ({
  GanttLegend: () => <div data-testid="gantt-legend" />,
}));
vi.mock('@/features/scheduling/components/GanttChart/GanttMachineRow', () => ({
  GanttMachineRow: ({ mc }: { mc: { id: string } }) => <div data-testid={`machine-row-${mc.id}`} />,
}));
vi.mock('@/features/scheduling/components/GanttChart/TimelineHeader', () => ({
  TimelineHeader: () => <div data-testid="timeline-header" />,
}));
vi.mock('@/features/scheduling/components/GanttChart/BlockDetailCard', () => ({
  BlockDetailCard: () => <div data-testid="block-detail" />,
}));
vi.mock('@/features/scheduling/components/GanttChart/DeviationPanel', () => ({
  DeviationPanel: () => <div data-testid="deviation-panel" />,
}));
vi.mock('@/features/scheduling/components/atoms', () => ({
  Card: ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => (
    <div data-testid="card" style={style}>
      {children}
    </div>
  ),
}));
vi.mock('@/theme/color-bridge', () => ({
  C: { t1: '#fff', t3: '#999', s1: '#111', ac: '#00f' },
}));

import { GanttView } from '@/features/scheduling/components/GanttChart/GanttChart';

const makeEngineData = (machines: Array<{ id: string; area: string }> = []) => ({
  ops: [],
  n_days: 1,
  machines,
  tools: [],
  toolMap: {},
  dates: ['2026-03-01'],
  dnames: ['Seg'],
  days_label: ['Seg'],
  mo: { PG1: [0], PG2: [0] },
  workday_flags: [true],
  workdays: [true],
  thirdShift: false,
});

describe('GanttView', () => {
  const baseProps = {
    blocks: [],
    mSt: {},
    cap: {},
    data: makeEngineData(),
    applyMove: vi.fn(),
    undoMove: vi.fn(),
  };

  it('renders without crashing with empty data', () => {
    const { container } = render(<GanttView {...baseProps} />);
    expect(container.querySelector('[role="region"]')).toBeInTheDocument();
  });

  it('shows empty state message when no blocks', () => {
    render(<GanttView {...baseProps} />);
    expect(screen.getByText(/Sem blocos schedulados/)).toBeInTheDocument();
  });

  it('renders machine rows when active machines exist', () => {
    const machines = [
      { id: 'PRM019', area: 'PG1' },
      { id: 'PRM031', area: 'PG1' },
    ];
    // Mutate the shared state so the hook returns active machines
    mockInteractionState.activeM = machines;

    render(
      <GanttView
        {...baseProps}
        data={makeEngineData(machines)}
        blocks={[
          {
            machineId: 'PRM019',
            toolId: 'T1',
            startMin: 420,
            endMin: 480,
            opId: 'op1',
            day: 0,
            qty: 100,
          } as any,
        ]}
      />,
    );

    expect(screen.getByTestId('machine-row-PRM019')).toBeInTheDocument();
    expect(screen.getByTestId('machine-row-PRM031')).toBeInTheDocument();

    // Reset
    mockInteractionState.activeM = [];
  });
});
