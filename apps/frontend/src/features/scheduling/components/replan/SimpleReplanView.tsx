import { RefreshCw, Settings2 } from 'lucide-react';
import type React from 'react';
import { useState } from 'react';
import type { MoveAction, ReplanDispatchResult } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { Card, dot } from '../atoms';
import { MachineDownPicker } from './MachineDownPicker';
import { SCENARIOS, type Scenario } from './replan-scenarios';

export function SimpleReplanView({
  machines,
  mSt,
  getResourceDownDays,
  setEditingDown,
  onRunAutoReplan,
  arRunning,
  arResult,
  arActionsCount,
  moves,
  onSwitchAdvanced,
  onDispatchReplan,
  replanRunning,
  replanResult,
}: {
  machines: { id: string; area: string }[];
  mSt: Record<string, string>;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
  onRunAutoReplan: () => void;
  arRunning: boolean;
  arResult: unknown;
  arActionsCount: number;
  moves: MoveAction[];
  onSwitchAdvanced: () => void;
  onDispatchReplan: (machineId: string, delayMin: number) => void;
  replanRunning: boolean;
  replanResult: ReplanDispatchResult | null;
}) {
  const [selected, setSelected] = useState<Scenario | null>(null);

  const downCount = machines.filter(
    (m) => mSt[m.id] === 'down' || getResourceDownDays('machine', m.id).size > 0,
  ).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Machine status overview */}
      <Card style={{ padding: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
          Estado das Máquinas
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {machines.map((m) => {
            const isDown = mSt[m.id] === 'down' || getResourceDownDays('machine', m.id).size > 0;
            const downDays = getResourceDownDays('machine', m.id);
            return (
              <div
                key={m.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 14px',
                  borderRadius: 8,
                  background: isDown ? C.rdS : `${C.ac}08`,
                  border: `1.5px solid ${isDown ? C.rd + '44' : C.ac + '22'}`,
                  minWidth: 120,
                }}
              >
                <span style={dot(isDown ? C.rd : C.ac)} aria-hidden="true" />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: isDown ? C.rd : C.t1, fontFamily: 'monospace' }}>
                    {m.id}
                  </div>
                  <div style={{ fontSize: 12, color: isDown ? C.rd : C.ac, fontWeight: 500 }}>
                    {isDown ? `Parada ${downDays.size}d` : 'Operacional'}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {downCount > 0 && (
          <div style={{ marginTop: 8, fontSize: 12, color: C.rd, fontWeight: 500 }}>
            {downCount} máquina{downCount > 1 ? 's' : ''} com problemas — replanear para
            redistribuir carga
          </div>
        )}
      </Card>

      {/* Scenario selection */}
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
                onClick={() => setSelected(isSel ? null : sc.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '12px 14px',
                  borderRadius: 8,
                  border: `1.5px solid ${isSel ? sc.color + '66' : C.bd}`,
                  background: isSel ? sc.color + '12' : 'transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontFamily: 'inherit',
                  transition: 'all .15s',
                }}
              >
                <div
                  style={{
                    width: 36, height: 36, borderRadius: 8,
                    background: sc.color + '18',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
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

      {selected === 'machine_down' && (
        <MachineDownPicker
          machines={machines}
          setEditingDown={setEditingDown}
          onSwitchAdvanced={onSwitchAdvanced}
          onDispatchReplan={onDispatchReplan}
          replanRunning={replanRunning}
          replanResult={replanResult}
        />
      )}

      {selected === 'tool_down' && (
        <Card style={{ padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Registar indisponibilidade de ferramenta
          </div>
          <div style={{ fontSize: 12, color: C.t3, marginBottom: 12 }}>
            Vai abrir o formulário detalhado para seleccionar a ferramenta e período
          </div>
          <button
            onClick={onSwitchAdvanced}
            style={{
              width: '100%', padding: 12, borderRadius: 8, border: 'none',
              background: C.yl, color: C.bg, fontSize: 13, fontWeight: 600,
              cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            Seleccionar ferramenta
          </button>
        </Card>
      )}

      {selected === 'rush_order' && (
        <Card style={{ padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Adicionar encomenda urgente
          </div>
          <div style={{ fontSize: 12, color: C.t3, marginBottom: 12 }}>
            Vai abrir o formulário para especificar a ferramenta, quantidade e prazo
          </div>
          <button
            onClick={onSwitchAdvanced}
            style={{
              width: '100%', padding: 12, borderRadius: 8, border: 'none',
              background: C.yl, color: C.bg, fontSize: 13, fontWeight: 600,
              cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            Adicionar encomenda
          </button>
        </Card>
      )}

      {selected === 'optimize' && (
        <Card style={{ padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Optimização automática
          </div>
          <div style={{ fontSize: 12, color: C.t3, marginBottom: 12 }}>
            Analisa o plano actual, redistribui operações entre máquinas e apresenta as melhorias
            possiveis com impacto em OTD-D e setups
          </div>
          <button
            onClick={onRunAutoReplan}
            disabled={arRunning}
            style={{
              width: '100%', padding: 12, borderRadius: 8, border: 'none',
              background: arRunning ? C.s3 : C.ac, color: arRunning ? C.t3 : C.bg,
              fontSize: 13, fontWeight: 600, cursor: arRunning ? 'wait' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <RefreshCw size={14} strokeWidth={1.5} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 6 }} />
            {arRunning ? 'A optimizar...' : 'Optimizar plano'}
          </button>
          {arResult != null && arActionsCount === 0 && (
            <div style={{ marginTop: 10, padding: '8px 12px', borderRadius: 6, background: C.acS, fontSize: 12, fontWeight: 600, color: C.ac }}>
              O plano actual ja esta na melhor configuracao possivel — sem redistribuicoes que
              melhorem OTD-D ou setups
            </div>
          )}
          {arResult != null && arActionsCount > 0 && (
            <div style={{ marginTop: 10, padding: '8px 12px', borderRadius: 6, background: `${C.ac}12`, border: `1px solid ${C.ac}33`, fontSize: 12, color: C.ac, fontWeight: 500 }}>
              {arActionsCount} melhorias encontradas.{' '}
              <button
                onClick={onSwitchAdvanced}
                style={{ background: 'none', border: 'none', color: C.ac, textDecoration: 'underline', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12, fontWeight: 600, padding: 0 }}
              >
                Ver detalhes
              </button>
            </div>
          )}
        </Card>
      )}

      {moves.length > 0 && (
        <Card style={{ padding: 16, background: C.acS, borderColor: C.ac + '33' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.ac }}>
            {moves.length} alteraç{moves.length > 1 ? 'ões' : 'ão'} pendente{moves.length > 1 ? 's' : ''}
          </div>
          <div style={{ fontSize: 12, color: C.t3, marginTop: 4 }}>
            Mude para o modo avançado para rever e aplicar as alterações
          </div>
        </Card>
      )}

      <button
        onClick={onSwitchAdvanced}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          padding: '10px 16px', borderRadius: 8, border: `1px solid ${C.bd}`,
          background: 'transparent', color: C.t3, fontSize: 12, fontWeight: 500,
          cursor: 'pointer', fontFamily: 'inherit',
        }}
      >
        <Settings2 size={13} strokeWidth={1.5} />
        Modo Avançado
      </button>
    </div>
  );
}
