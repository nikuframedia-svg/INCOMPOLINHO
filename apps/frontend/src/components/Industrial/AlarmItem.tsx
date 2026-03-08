import type { ReactNode } from 'react';
import { ALARM_PRIORITY } from '../../theme/production-colors';
import '../../theme/base-components.css';

export type AlarmPriority = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type AlarmState = 'flash' | 'solid';

export interface AlarmAction {
  label: string;
  onClick: () => void;
}

export interface AlarmItemProps {
  priority: AlarmPriority;
  state?: AlarmState;
  title: string;
  detail?: string;
  icon?: ReactNode;
  actions?: AlarmAction[];
}

export function AlarmItem({
  priority,
  state = 'solid',
  title,
  detail,
  icon,
  actions,
}: AlarmItemProps) {
  const color = ALARM_PRIORITY[priority];
  const flash = state === 'flash' && (priority === 'critical' || priority === 'high');

  return (
    <div
      className="alarm-item"
      style={{ borderLeftColor: color, background: `${color}08` }}
      data-testid={`alarm-${priority}`}
    >
      {icon ?? (
        <span
          className={`alarm-item__indicator${flash ? ' alarm-item__indicator--flash' : ''}`}
          style={{ background: color }}
        />
      )}
      <div className="alarm-item__content">
        <span className="alarm-item__title">{title}</span>
        {detail && <span className="alarm-item__detail">{detail}</span>}
      </div>
      {actions && actions.length > 0 && (
        <div className="alarm-item__actions">
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              className="alarm-item__action-btn"
              onClick={a.onClick}
              data-testid={`alarm-action-${a.label}`}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
