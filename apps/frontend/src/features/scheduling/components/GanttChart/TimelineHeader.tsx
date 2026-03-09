import { C, S0, S1, T1 } from '../../../../lib/engine';

export interface TimelineHeaderProps {
  hours: number[];
  ppm: number;
  selDay: number;
  dnames: string[];
  dates: string[];
}

export function TimelineHeader({ hours, ppm, selDay, dnames, dates }: TimelineHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        position: 'sticky',
        top: 0,
        zIndex: 10,
        background: C.s1,
        borderBottom: `1px solid ${C.bd}`,
      }}
    >
      <div
        style={{
          width: 100,
          minWidth: 100,
          padding: '8px 10px',
          borderRight: `1px solid ${C.bd}`,
          fontSize: 11,
          fontWeight: 600,
          color: C.t2,
        }}
      >
        {dnames[selDay]} {dates[selDay]}
      </div>
      <div style={{ position: 'relative', height: 28, flex: 1 }}>
        {hours.map((h) => {
          const x = (h * 60 - S0) * ppm;
          return (
            <div
              key={h}
              style={{
                position: 'absolute',
                left: x,
                top: 0,
                height: '100%',
                borderLeft: `1px solid ${C.bd}${h % 2 === 0 ? '' : '44'}`,
              }}
            >
              <span
                style={{
                  fontSize: 9,
                  color: h % 2 === 0 ? C.t3 : C.t4,
                  fontFamily: 'monospace',
                  position: 'absolute',
                  bottom: 3,
                  left: 4,
                }}
              >
                {String(h).padStart(2, '0')}:00
              </span>
            </div>
          );
        })}
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: (T1 - S0) * ppm,
            height: '100%',
            background: `${C.ac}04`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: (T1 - S0) * ppm,
            top: 0,
            width: (S1 - T1) * ppm,
            height: '100%',
            background: `${C.bl}04`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: (T1 - S0) * ppm,
            top: 0,
            height: '100%',
            borderLeft: `2px solid ${C.yl}66`,
          }}
        >
          <span
            style={{
              fontSize: 7,
              color: C.yl,
              position: 'absolute',
              top: 2,
              left: 4,
              fontWeight: 600,
            }}
          >
            T.Y
          </span>
        </div>
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: 4,
            fontSize: 7,
            color: C.ac,
            fontWeight: 600,
            opacity: 0.6,
          }}
        >
          T.X
        </span>
      </div>
    </div>
  );
}
