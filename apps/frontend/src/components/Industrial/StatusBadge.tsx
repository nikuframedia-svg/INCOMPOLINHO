import type { ReactNode } from 'react';
import { ALARM_PRIORITY, EQUIPMENT_STATE, GANTT_STATUS } from '../../theme/production-colors';
import '../../theme/base-components.css';

type StatusVariant =
  | 'running'
  | 'stopped'
  | 'transition'
  | 'manual'
  | 'outOfService'
  | 'critical'
  | 'high'
  | 'medium'
  | 'low'
  | 'info'
  | 'ontime'
  | 'late'
  | 'atRisk'
  | 'setup'
  | 'blocked'
  | 'overflow';

const COLOR_MAP: Record<StatusVariant, string> = {
  ...EQUIPMENT_STATE,
  ...ALARM_PRIORITY,
  ontime: GANTT_STATUS.ontime,
  late: GANTT_STATUS.late,
  atRisk: GANTT_STATUS.atRisk,
  setup: GANTT_STATUS.setup,
  blocked: GANTT_STATUS.blocked,
  overflow: GANTT_STATUS.overflow,
};

const BG_MAP: Record<StatusVariant, string> = Object.fromEntries(
  Object.entries(COLOR_MAP).map(([k, color]) => [k, `${color}18`]),
) as Record<StatusVariant, string>;

export interface StatusBadgeProps {
  variant: StatusVariant;
  label: string;
  icon?: ReactNode;
}

export function StatusBadge({ variant, label, icon }: StatusBadgeProps) {
  const color = COLOR_MAP[variant];
  const bg = BG_MAP[variant];

  return (
    <span
      className="status-badge"
      style={{ color, background: bg }}
      data-testid={`status-badge-${variant}`}
    >
      {icon ?? <span className="status-badge__dot" style={{ background: color }} />}
      {label}
    </span>
  );
}
