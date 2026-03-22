import { C } from '@/theme/color-bridge';
import { Card } from '../atoms';
import { SCENARIOS, type Scenario } from './replan-scenarios';

export function ReplanScenarioList({
  selected,
  onSelect,
}: {
  selected: Scenario | null;
  onSelect: (sc: Scenario | null) => void;
}) {
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: C.t1, marginBottom: 4 }}>
        O que aconteceu?
      </div>
      <div style={{ fontSize: 12, color: C.t3, marginBottom: 12 }}>
        Seleccione o cenário e o sistema resolve automaticamente
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {SCENARIOS.map((sc) => {
          const Icon = sc.icon;
          const isSel = selected === sc.id;
          return (
            <button
              key={sc.id}
              onClick={() => onSelect(isSel ? null : sc.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '12px 14px',
                borderRadius: 8,
                border: `1.5px solid ${isSel ? `${sc.color}66` : C.bd}`,
                background: isSel ? `${sc.color}12` : 'transparent',
                cursor: 'pointer',
                textAlign: 'left',
                fontFamily: 'inherit',
                transition: 'all .15s',
              }}
            >
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 8,
                  background: `${sc.color}18`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <Icon size={18} strokeWidth={1.5} style={{ color: sc.color }} />
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: isSel ? sc.color : C.t1 }}>
                  {sc.label}
                </div>
                <div style={{ fontSize: 12, color: C.t3, marginTop: 1 }}>{sc.desc}</div>
              </div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
