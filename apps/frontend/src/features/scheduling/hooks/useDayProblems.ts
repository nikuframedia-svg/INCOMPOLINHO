/**
 * useDayProblems — Derives human-readable problem descriptions for a selected day.
 * Each problem is a full Portuguese sentence with machine, SKU, and consequence.
 */

import { useMemo } from 'react';
import type { Block, ScheduleValidationReport, ScheduleViolation } from '../../../lib/engine';

export interface DayProblem {
  id: string;
  severity: 'critical' | 'high' | 'medium';
  machineId?: string;
  text: string;
  consequence?: string;
  actionLabel?: string;
}

function violationToSentence(v: ScheduleViolation, dnames: string[], dates: string[]): string {
  const affectedMachines = [...new Set(v.affectedOps.map((o) => o.machineId))];
  const affectedTools = [...new Set(v.affectedOps.map((o) => o.toolId))];
  const machineStr = affectedMachines.join(', ');
  const toolStr = affectedTools.slice(0, 2).join(', ');

  switch (v.type) {
    case 'TOOL_UNIQUENESS':
      return `${machineStr}: Conflito de ferramenta — ${toolStr} está em 2 máquinas ao mesmo tempo.`;
    case 'SETUP_CREW_OVERLAP':
      return `${machineStr}: Dois setups sobrepostos — so ha uma equipa de setup.`;
    case 'MACHINE_OVERCAPACITY':
      return `${machineStr}: Carga excede capacidade — lotes ultrapassam o turno disponivel.`;
    case 'DEADLINE_MISS': {
      const days = [...new Set(v.affectedOps.map((o) => o.dayIdx))].sort((a, b) => a - b);
      const dayStr = days.map((d) => `${dnames[d] ?? '?'} ${dates[d] ?? ''}`).join(', ');
      return `${machineStr}: Lote ${toolStr} ultrapassa prazo — entrega ${dayStr} em risco.`;
    }
    default:
      return `${machineStr}: ${v.title}. ${v.detail}`;
  }
}

function violationConsequence(v: ScheduleViolation): string | undefined {
  switch (v.type) {
    case 'TOOL_UNIQUENESS':
      return 'Uma das máquinas terá de esperar — atraso em cascata.';
    case 'SETUP_CREW_OVERLAP':
      return 'Um dos setups tera de ser adiado.';
    case 'MACHINE_OVERCAPACITY':
      return 'Produção pode não concluir no turno planeado.';
    case 'DEADLINE_MISS':
      return 'Entrega ao cliente pode atrasar.';
    default:
      return v.suggestedFix ?? undefined;
  }
}

export function useDayProblems(
  validation: ScheduleValidationReport | null,
  blocks: Block[],
  selDay: number,
  mSt: Record<string, string>,
  dnames: string[],
  dates: string[],
): DayProblem[] {
  return useMemo(() => {
    const problems: DayProblem[] = [];

    // 1. Violations for this day
    if (validation) {
      for (const v of validation.violations) {
        const touchesDay = v.affectedOps.some((o) => o.dayIdx === selDay);
        if (!touchesDay) continue;
        const machines = [...new Set(v.affectedOps.filter((o) => o.dayIdx === selDay).map((o) => o.machineId))];
        problems.push({
          id: v.id,
          severity: v.severity === 'critical' ? 'critical' : v.severity === 'high' ? 'high' : 'medium',
          machineId: machines[0],
          text: violationToSentence(v, dnames, dates),
          consequence: violationConsequence(v),
          actionLabel: v.action ? `Mover para ${v.action.toM}` : undefined,
        });
      }
    }

    // 2. Machines that are down
    const dayBlocks = blocks.filter((b) => b.dayIdx === selDay && b.type !== 'blocked');
    const dayMachines = [...new Set(dayBlocks.map((b) => b.machineId))];
    for (const mId of dayMachines) {
      if (mSt[mId] !== 'down') continue;
      const affected = dayBlocks.filter((b) => b.machineId === mId).length;
      // Only add if not already covered by a violation
      const alreadyCovered = problems.some((p) => p.machineId === mId);
      if (alreadyCovered) continue;
      problems.push({
        id: `down-${mId}`,
        severity: 'critical',
        machineId: mId,
        text: `${mId}: Máquina parada — ${affected} lote${affected !== 1 ? 's' : ''} afectado${affected !== 1 ? 's' : ''} neste dia.`,
        consequence: 'Produção parada até recuperação. Lotes podem necessitar redistribuição.',
      });
    }

    // 3. Overflow blocks for this day
    const overflowBlocks = dayBlocks.filter((b) => b.overflow);
    if (overflowBlocks.length > 0) {
      const machines = [...new Set(overflowBlocks.map((b) => b.machineId))];
      const alreadyCovered = problems.some((p) => p.id.startsWith('MACHINE_OVERCAPACITY'));
      if (!alreadyCovered) {
        problems.push({
          id: `overflow-day-${selDay}`,
          severity: 'high',
          machineId: machines[0],
          text: `${overflowBlocks.length} lote${overflowBlocks.length !== 1 ? 's' : ''} em ${machines.join(', ')} excedem a capacidade do turno.`,
          consequence: 'Pode ser necessario turno extra ou redistribuicao.',
        });
      }
    }

    // Sort by severity
    const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2 };
    problems.sort((a, b) => (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3));

    return problems;
  }, [validation, blocks, selDay, mSt, dnames, dates]);
}
