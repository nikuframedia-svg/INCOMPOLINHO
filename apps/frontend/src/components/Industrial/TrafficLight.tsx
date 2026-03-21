import { Tooltip } from 'antd';
import '../../theme/base-components.css';

export type TrafficLightState = 'green' | 'yellow' | 'red';

export interface TrafficLightProps {
  state: TrafficLightState;
  thresholds?: { green: string; yellow: string; red: string };
  size?: 'mini' | 'normal';
}

const BULB_COLORS: Record<TrafficLightState, string> = {
  red: 'var(--semantic-red)',
  yellow: 'var(--semantic-amber)',
  green: 'var(--semantic-green)',
};

const BULBS: TrafficLightState[] = ['red', 'yellow', 'green'];

export function TrafficLight({ state, thresholds, size = 'normal' }: TrafficLightProps) {
  const bulbSize = size === 'mini' ? 8 : 16;

  const content = (
    <div className={`traffic-light traffic-light--${size}`} data-testid={`traffic-light-${state}`}>
      {BULBS.map((bulb) => (
        <div
          key={bulb}
          className={`traffic-light__bulb ${bulb !== state ? 'traffic-light__bulb--dim' : ''}`}
          style={{
            width: bulbSize,
            height: bulbSize,
            background: BULB_COLORS[bulb],
          }}
        />
      ))}
    </div>
  );

  if (!thresholds) return content;

  const tooltipContent = (
    <div style={{ fontSize: 12 }}>
      <div style={{ color: 'var(--semantic-green)' }}>{thresholds.green}</div>
      <div style={{ color: 'var(--semantic-amber)' }}>{thresholds.yellow}</div>
      <div style={{ color: 'var(--semantic-red)' }}>{thresholds.red}</div>
    </div>
  );

  return <Tooltip title={tooltipContent}>{content}</Tooltip>;
}
