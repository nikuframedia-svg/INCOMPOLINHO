import { useState } from 'react';
import { Settings2, Wrench, RefreshCw, Target, Zap } from 'lucide-react';
import { C } from '../../../../lib/engine';
import { Card } from '../atoms';

// ── Quick scenario presets for simple mode ──
const QUICK_SCENARIOS = [
  {
    id: 'optimize',
    icon: RefreshCw,
    label: 'Optimizar plano',
    desc: 'Equilibra OTD-D, setups e utilização — mostra trade-offs',
    color: C.ac,
    profile: 'balanced',
  },
  {
    id: 'otd',
    icon: Target,
    label: 'Maximizar entregas',
    desc: 'Prioriza entregas a tempo — pode aumentar setups',
    color: C.bl,
    profile: 'otd',
  },
  {
    id: 'setup',
    icon: Zap,
    label: 'Minimizar setups',
    desc: 'Agrupa ferramentas — pode atrasar entregas menos urgentes',
    color: C.pp,
    profile: 'setup',
  },
  {
    id: 'breakdown',
    icon: Wrench,
    label: 'Simular avaria',
    desc: 'Mostra que entregas sao afectadas e redistribui carga',
    color: C.rd,
    profile: null,
  },
] as const;

export function SimpleWhatIfView({
  run,
  prog,
  res,
  onOptimize,
  onSelectProfile,
  onSwitchAdvanced,
  setResourceDown,
  setRes,
  focusIds,
}: {
  run: boolean;
  prog: number;
  res: unknown;
  onOptimize: () => void;
  onSelectProfile: (id: string) => void;
  onSwitchAdvanced: () => void;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  setRes: (r: null) => void;
  focusIds: string[];
}) {
  const [scenario, setScenario] = useState<string | null>(null);
  const [selectedMachine, setSelectedMachine] = useState<string | null>(null);

  const handleScenario = (id: string) => {
    const preset = QUICK_SCENARIOS.find((s) => s.id === id);
    if (!preset) return;
    if (id === 'breakdown') {
      setScenario('breakdown');
      return;
    }
    if (preset.profile) onSelectProfile(preset.profile);
    setScenario(id);
    onOptimize();
  };

  const handleBreakdownMachine = (mId: string) => {
    setSelectedMachine(mId);
    setResourceDown('machine', mId, [0, 1]);
    setRes(null);
    onSelectProfile('otd');
    onOptimize();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Hero card */}
      <Card style={{ padding: 24, textAlign: 'center' }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: C.t1, marginBottom: 6 }}>
          Simulação What-If
        </div>
        <div style={{ fontSize: 12, color: C.t3, maxWidth: 420, margin: '0 auto', lineHeight: 1.6 }}>
          Compara cenarios alternativos lado a lado. Cada opcao mostra o impacto em entregas, setups e utilização antes de aplicar.
        </div>
      </Card>

      {/* Scenario cards */}
      {!run && res == null && scenario !== 'breakdown' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {QUICK_SCENARIOS.map((s) => (
            <Card
              key={s.id}
              style={{
                padding: 20,
                cursor: 'pointer',
                transition: 'transform .15s, border-color .15s',
                border: `1px solid ${C.bd}`,
              }}
              onClick={() => handleScenario(s.id)}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.borderColor = s.color;
                (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.borderColor = C.bd;
                (e.currentTarget as HTMLElement).style.transform = 'translateY(0)';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    background: s.color + '18',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <s.icon size={20} color={s.color} />
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>{s.label}</div>
                  <div style={{ fontSize: 12, color: C.t3, marginTop: 2 }}>{s.desc}</div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Breakdown machine picker */}
      {scenario === 'breakdown' && !run && res == null && (
        <Card style={{ padding: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
            Qual máquina está parada?
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {focusIds.map((mId) => (
              <button
                key={mId}
                onClick={() => handleBreakdownMachine(mId)}
                style={{
                  padding: '10px 20px',
                  borderRadius: 8,
                  border: `1px solid ${selectedMachine === mId ? C.rd : C.bd}`,
                  background: selectedMachine === mId ? C.rd + '18' : C.s1,
                  color: C.t1,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  transition: 'all .15s',
                }}
              >
                {mId}
              </button>
            ))}
          </div>
          <button
            onClick={() => setScenario(null)}
            style={{
              marginTop: 12,
              background: 'none',
              border: 'none',
              color: C.t3,
              fontSize: 12,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Voltar
          </button>
        </Card>
      )}

      {/* Running state — greedy phase */}
      {run && (
        <Card style={{ padding: 32, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.ac, marginBottom: 12 }}>
            Fase 1 — Grid search...
          </div>
          <div style={{ width: '100%', height: 8, borderRadius: 4, background: C.s2, overflow: 'hidden', marginBottom: 8 }}>
            <div style={{ height: '100%', width: `${prog}%`, background: C.ac, borderRadius: 4, transition: 'width .15s' }} />
          </div>
          <div style={{ fontSize: 12, color: C.t3 }}>{prog}% concluído</div>
        </Card>
      )}

      {/* Modo Avançado button */}
      <button
        onClick={onSwitchAdvanced}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 6,
          padding: 12,
          borderRadius: 8,
          border: `1px solid ${C.bd}`,
          background: 'transparent',
          color: C.t3,
          fontSize: 12,
          cursor: 'pointer',
          fontFamily: 'inherit',
          transition: 'border-color .15s',
        }}
      >
        <Settings2 size={14} />
        Modo Avançado
      </button>
    </div>
  );
}
