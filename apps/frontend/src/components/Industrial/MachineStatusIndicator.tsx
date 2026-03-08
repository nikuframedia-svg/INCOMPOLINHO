import { EQUIPMENT_STATE } from '../../theme/production-colors';
import '../../theme/base-components.css';

export type MachineState = 'running' | 'stopped' | 'transition' | 'manual' | 'outOfService';

const STATE_LABELS: Record<MachineState, string> = {
  running: 'Em producao',
  stopped: 'Parada',
  transition: 'Transicao',
  manual: 'Manual',
  outOfService: 'Fora de servico',
};

export interface MachineStatusIndicatorProps {
  state: MachineState;
  machineId?: string;
  compact?: boolean;
}

export function MachineStatusIndicator({ state, machineId, compact }: MachineStatusIndicatorProps) {
  const color = EQUIPMENT_STATE[state];
  const animated = state === 'running' || state === 'transition';

  return (
    <span
      className="machine-status"
      style={{ background: `${color}12` }}
      data-testid={`machine-status-${machineId ?? state}`}
    >
      <span
        className={`machine-status__pulse${animated ? ' machine-status__pulse--animated' : ''}`}
        style={{ background: color }}
      />
      {!compact && (
        <span style={{ color }}>
          {machineId ? `${machineId} · ` : ''}
          {STATE_LABELS[state]}
        </span>
      )}
    </span>
  );
}
