import { memo } from 'react';
import { EQUIPMENT_STATE } from '../../theme/production-colors';
import '../../theme/base-components.css';

export type MachineState =
  | 'running'
  | 'stopped'
  | 'transition'
  | 'manual'
  | 'outOfService'
  | 'maintenance'
  | 'idle';

const STATE_LABELS: Record<MachineState, string> = {
  running: 'Em produção',
  stopped: 'Parada',
  transition: 'Transicao',
  manual: 'Manual',
  outOfService: 'Fora de servico',
  maintenance: 'Manutencao',
  idle: 'Disponivel',
};

export interface MachineStatusIndicatorProps {
  state: MachineState;
  machineId?: string;
  compact?: boolean;
}

export const MachineStatusIndicator = memo(function MachineStatusIndicator({ state, machineId, compact }: MachineStatusIndicatorProps) {
  const color = EQUIPMENT_STATE[state];
  const animated = state === 'running' || state === 'transition' || state === 'maintenance';

  return (
    <span
      className="machine-status"
      style={{ background: `${color}12` }}
      role="status"
      aria-label={STATE_LABELS[state]}
      data-testid={`machine-status-${machineId ?? state}`}
    >
      <span
        className={`machine-status__pulse${animated ? ' machine-status__pulse--animated' : ''}`}
        style={{ background: color }}
        aria-hidden="true"
      />
      {compact && <span className="sr-only">{STATE_LABELS[state]}</span>}
      {!compact && (
        <span style={{ color }}>
          {machineId ? `${machineId} · ` : ''}
          {STATE_LABELS[state]}
        </span>
      )}
    </span>
  );
});
