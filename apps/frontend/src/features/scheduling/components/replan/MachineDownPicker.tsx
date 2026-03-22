import type React from 'react';
import { useState } from 'react';
import { LAYER_THRESHOLD_1, LAYER_THRESHOLD_2 } from '@/utils/replan-helpers';
import type { ReplanDispatchResult, ReplanLayer } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { Card } from '../atoms';

const DURATION_PRESETS = [
  { label: '30 min', min: 30 },
  { label: '1 hora', min: 60 },
  { label: '2 horas', min: 120 },
  { label: 'Dia inteiro', min: 510 },
] as const;

const LAYER_LABELS: Record<ReplanLayer, string> = {
  1: 'Right-shift',
  2: 'Match-up',
  3: 'Parcial',
  4: 'Regeneração total',
};

export function MachineDownPicker({
  machines,
  setEditingDown,
  onSwitchAdvanced,
  onDispatchReplan,
  replanRunning,
  replanResult,
}: {
  machines: { id: string; area: string }[];
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
  onSwitchAdvanced: () => void;
  onDispatchReplan: (machineId: string, delayMin: number) => void;
  replanRunning: boolean;
  replanResult: ReplanDispatchResult | null;
}) {
  const [selectedMachine, setSelectedMachine] = useState<string | null>(null);
  const [selectedDuration, setSelectedDuration] = useState<number | null>(null);

  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Qual máquina está parada?
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {machines.map((m) => {
          const isSel = selectedMachine === m.id;
          return (
            <button
              key={m.id}
              onClick={() => {
                setSelectedMachine(isSel ? null : m.id);
                setSelectedDuration(null);
              }}
              style={{
                padding: '10px 16px',
                borderRadius: 8,
                border: `1.5px solid ${isSel ? `${C.rd}66` : C.bd}`,
                background: isSel ? C.rdS : 'transparent',
                cursor: 'pointer',
                fontFamily: 'monospace',
                fontSize: 14,
                fontWeight: 600,
                color: isSel ? C.rd : C.t1,
                transition: 'all .15s',
              }}
            >
              {m.id}
              <div style={{ fontSize: 12, fontWeight: 400, color: C.t3, marginTop: 2 }}>
                {m.area}
              </div>
            </button>
          );
        })}
      </div>

      {selectedMachine && (
        <>
          <div
            style={{ fontSize: 13, fontWeight: 600, color: C.t1, marginBottom: 8, marginTop: 4 }}
          >
            Duração estimada da paragem
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {DURATION_PRESETS.map((p) => {
              const isSel = selectedDuration === p.min;
              const layer = p.min < LAYER_THRESHOLD_1 ? 1 : p.min < LAYER_THRESHOLD_2 ? 2 : 3;
              return (
                <button
                  key={p.min}
                  onClick={() => setSelectedDuration(isSel ? null : p.min)}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 8,
                    border: `1.5px solid ${isSel ? `${C.rd}66` : C.bd}`,
                    background: isSel ? C.rdS : 'transparent',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    fontSize: 13,
                    fontWeight: 600,
                    color: isSel ? C.rd : C.t1,
                    transition: 'all .15s',
                  }}
                >
                  {p.label}
                  <div style={{ fontSize: 12, fontWeight: 400, color: C.t3, marginTop: 2 }}>
                    Camada {layer}
                  </div>
                </button>
              );
            })}
          </div>
        </>
      )}

      {selectedMachine && selectedDuration != null && (
        <button
          onClick={() => onDispatchReplan(selectedMachine, selectedDuration)}
          disabled={replanRunning}
          style={{
            width: '100%',
            padding: 12,
            borderRadius: 8,
            border: 'none',
            background: replanRunning ? C.s3 : C.rd,
            color: replanRunning ? C.t3 : 'var(--text-inverse, #fff)',
            fontSize: 13,
            fontWeight: 600,
            cursor: replanRunning ? 'wait' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {replanRunning
            ? 'A replanear...'
            : `Replanear ${selectedMachine} (${DURATION_PRESETS.find((p) => p.min === selectedDuration)?.label})`}
        </button>
      )}

      {replanResult && (
        <div
          style={{
            marginTop: 10,
            padding: '10px 14px',
            borderRadius: 8,
            background: replanResult.emergencyNightShift ? C.rdS : C.acS,
            border: `1px solid ${replanResult.emergencyNightShift ? `${C.rd}33` : `${C.ac}33`}`,
          }}
        >
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: replanResult.emergencyNightShift ? C.rd : C.ac,
            }}
          >
            Camada {replanResult.layer}: {LAYER_LABELS[replanResult.layer]}
          </div>
          <div style={{ fontSize: 12, color: C.t2, marginTop: 4 }}>
            {replanResult.blocks.length} blocos resequenciados
            {replanResult.emergencyNightShift && ' — turno noite de emergência necessário'}
          </div>
        </div>
      )}

      {selectedMachine && (
        <button
          onClick={() => {
            setEditingDown({ type: 'machine', id: selectedMachine });
            onSwitchAdvanced();
          }}
          style={{
            width: '100%',
            marginTop: 8,
            padding: 10,
            borderRadius: 8,
            border: `1px solid ${C.bd}`,
            background: 'transparent',
            color: C.t3,
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Configuração avançada (dias específicos)
        </button>
      )}
    </Card>
  );
}
