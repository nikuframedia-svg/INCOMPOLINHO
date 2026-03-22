/**
 * AlertsPanel.test.tsx — AlertsPanel component tests.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/domain/types/scheduling', () => ({
  C: { ac: '#3B82F6', yl: '#F59E0B', rd: '#EF4444' },
}));

import type { InfeasibilityEntry, ScheduleViolation } from '@/domain/types/scheduling';
import { AlertsPanel } from '@/features/console/components/AlertsPanel';

const mkV = (
  ov: Partial<ScheduleViolation> & Pick<ScheduleViolation, 'id' | 'severity' | 'title' | 'detail'>,
): ScheduleViolation => ({
  type: 'SETUP_CREW_OVERLAP',
  affectedOps: [],
  suggestedFix: null,
  action: null,
  ...ov,
});

const mkI = (
  ov: Partial<InfeasibilityEntry> &
    Pick<InfeasibilityEntry, 'opId' | 'machineId' | 'toolId' | 'reason' | 'detail'>,
): InfeasibilityEntry => ({
  attemptedAlternatives: [],
  suggestion: '',
  ...ov,
});

describe('AlertsPanel', () => {
  it('renders empty state when no alerts', () => {
    render(<AlertsPanel violations={[]} infeasibilities={[]} />);
    expect(screen.getByTestId('alerts-panel')).toBeInTheDocument();
  });

  it('renders infeasibility entries', () => {
    render(
      <AlertsPanel
        violations={[]}
        infeasibilities={[
          mkI({
            opId: 'op1',
            machineId: 'PRM019',
            toolId: 'T100',
            reason: 'CAPACITY_OVERFLOW',
            detail: 'Sem capacidade',
            suggestion: 'Mover para PRM031',
          }),
        ]}
      />,
    );
    expect(screen.getByText('INFEASIBLE')).toBeInTheDocument();
    expect(screen.getByText('Mover para PRM031')).toBeInTheDocument();
  });

  it('renders violation entries with severity', () => {
    render(
      <AlertsPanel
        violations={[
          mkV({
            id: 'v1',
            severity: 'medium',
            title: 'Setup crew overlap',
            detail: 'detail',
            suggestedFix: 'Desfasar 30 min',
          }),
        ]}
        infeasibilities={[]}
      />,
    );
    expect(screen.getByText('MEDIUM')).toBeInTheDocument();
    expect(screen.getByText('Setup crew overlap')).toBeInTheDocument();
  });

  it('renders mixed infeasibilities and violations', () => {
    render(
      <AlertsPanel
        violations={[mkV({ id: 'v1', severity: 'critical', title: 'Overlap', detail: 'd1' })]}
        infeasibilities={[
          mkI({
            opId: 'op1',
            machineId: 'PRM019',
            toolId: 'T1',
            reason: 'CAPACITY_OVERFLOW',
            detail: 'Infeasible op',
          }),
        ]}
      />,
    );
    expect(screen.getByText('INFEASIBLE')).toBeInTheDocument();
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
  });

  it('displays feasibility score when below 100%', () => {
    render(
      <AlertsPanel
        violations={[mkV({ id: 'v1', severity: 'medium', title: 'T', detail: 'D' })]}
        infeasibilities={[]}
        feasibilityScore={0.85}
      />,
    );
    expect(screen.getByText('Viabilidade')).toBeInTheDocument();
    expect(screen.getByText('85%')).toBeInTheDocument();
  });

  it('hides feasibility score at 100%', () => {
    render(<AlertsPanel violations={[]} infeasibilities={[]} feasibilityScore={1.0} />);
    expect(screen.queryByText('Viabilidade')).not.toBeInTheDocument();
  });
});
