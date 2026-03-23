/**
 * SimulatorPanel — unified scenario simulation UI.
 * Replaces ReplanPanel + WhatIfPanel.
 */

import { Loader2, Play, RotateCcw, Save } from 'lucide-react';
import type { EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import type { SimMutation } from '../../../../lib/api';
import type { SimMutationImpact, SimulatorState } from '../../hooks/useSimulator';
import { AddMutationMenu } from './AddMutationMenu';
import { DeltaTable } from './DeltaTable';
import { MutationCard } from './MutationCard';
import { SummaryText } from './SummaryText';

interface Props {
  engineData: EngineData;
  onApply?: (blocks: unknown[], score: Record<string, unknown>) => void;
  /** Simulator state — lifted from useSimulator() in parent */
  sim: SimulatorState & {
    addMutation: (mut: SimMutation) => void;
    removeMutation: (idx: number) => void;
    updateMutation: (idx: number, mut: SimMutation) => void;
    clearAll: () => void;
    simulate: () => Promise<void>;
  };
}

export function SimulatorPanel({ engineData, onApply, sim }: Props) {
  const impactMap = new Map<number, SimMutationImpact>();
  if (sim.result) {
    for (const imp of sim.result.mutation_impacts) {
      impactMap.set(imp.mutation_idx, imp);
    }
  }

  const handleApply = () => {
    if (!sim.result || !onApply) return;
    onApply(sim.result.blocks, (sim.result.score ?? {}) as Record<string, unknown>);
    sim.clearAll();
  };

  return (
    <div style={{ maxWidth: 520 }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <h3
          style={{ fontSize: 14, fontWeight: 700, color: C.t1, margin: 0, letterSpacing: '.02em' }}
        >
          SIMULADOR DE CENÁRIOS
        </h3>
        {sim.mutations.length > 0 && (
          <button
            onClick={sim.clearAll}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '4px 10px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: 'transparent',
              color: C.t3,
              fontSize: 11,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <RotateCcw size={12} /> Limpar
          </button>
        )}
      </div>

      {/* Mutation stack */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
        {sim.mutations.map((mut, i) => (
          <MutationCard
            key={i}
            mutation={mut}
            index={i}
            impact={impactMap.get(i)}
            engineData={engineData}
            onUpdate={sim.updateMutation}
            onRemove={sim.removeMutation}
          />
        ))}
      </div>

      {/* Add mutation */}
      <div style={{ marginBottom: 16 }}>
        <AddMutationMenu onAdd={sim.addMutation} />
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button
          onClick={sim.simulate}
          disabled={sim.running || sim.mutations.length === 0}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '8px 20px',
            borderRadius: 6,
            border: 'none',
            background: sim.running || sim.mutations.length === 0 ? C.t4 : C.ac,
            color: sim.running || sim.mutations.length === 0 ? C.t3 : C.bg,
            fontSize: 13,
            fontWeight: 700,
            cursor: sim.running || sim.mutations.length === 0 ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {sim.running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          {sim.running ? 'A simular...' : 'SIMULAR'}
        </button>
        {sim.result && onApply && (
          <button
            onClick={handleApply}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 20px',
              borderRadius: 6,
              border: `1px solid ${C.ac}44`,
              background: `${C.ac}10`,
              color: C.ac,
              fontSize: 13,
              fontWeight: 700,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <Save size={14} /> APLICAR AO PLANO
          </button>
        )}
      </div>

      {/* Error */}
      {sim.error && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            background: `${C.rd}12`,
            border: `1px solid ${C.rd}33`,
            color: C.rd,
            fontSize: 12,
            marginBottom: 12,
          }}
        >
          {sim.error}
        </div>
      )}

      {/* Results */}
      {sim.result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Timing badge */}
          <div style={{ fontSize: 11, color: C.t3 }}>
            Simulação em {sim.result.time_ms.toFixed(0)} ms
            {sim.result.mutation_impacts.length > 0 &&
              ` · ${sim.result.mutation_impacts.length} impactos calculados`}
          </div>

          {/* Delta table */}
          <DeltaTable delta={sim.result.delta} />

          {/* Summary */}
          <SummaryText lines={sim.result.summary} />

          {/* Block changes summary */}
          {sim.result.block_changes.length > 0 && (
            <div style={{ fontSize: 11, color: C.t3 }}>
              {sim.result.block_changes.filter((c) => c.action === 'moved').length} movidos,{' '}
              {sim.result.block_changes.filter((c) => c.action === 'new').length} novos,{' '}
              {sim.result.block_changes.filter((c) => c.action === 'removed').length} removidos
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {sim.mutations.length === 0 && !sim.result && (
        <div style={{ padding: '24px 0', textAlign: 'center', color: C.t3, fontSize: 12 }}>
          Adicione mutações para simular cenários.
          <br />
          <span style={{ fontSize: 11 }}>Ex: máquina parada + encomenda urgente + 3º turno</span>
        </div>
      )}
    </div>
  );
}
