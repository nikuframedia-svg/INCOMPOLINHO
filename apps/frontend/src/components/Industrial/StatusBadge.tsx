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

export type StatusBadgeSize = 'small' | 'medium' | 'large';

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
  size?: StatusBadgeSize;
}

const SIZE_STYLES: Record<StatusBadgeSize, { dot: number; fontSize: number; padding: string }> = {
  small: { dot: 6, fontSize: 12, padding: '1px 6px' },
  medium: { dot: 8, fontSize: 12, padding: '2px 8px' },
  large: { dot: 10, fontSize: 13, padding: '3px 10px' },
};

export function StatusBadge({ variant, label, icon, size = 'medium' }: StatusBadgeProps) {
  const color = COLOR_MAP[variant];
  const bg = BG_MAP[variant];
  const sizeStyle = SIZE_STYLES[size];

  return (
    <span
      className={`status-badge status-badge--${size}`}
      style={{ color, background: bg, fontSize: sizeStyle.fontSize, padding: sizeStyle.padding }}
      data-testid={`status-badge-${variant}`}
    >
      {icon ?? (
        <span
          className="status-badge__dot"
          style={{ background: color, width: sizeStyle.dot, height: sizeStyle.dot }}
        />
      )}
      {label}
    </span>
  );
}
