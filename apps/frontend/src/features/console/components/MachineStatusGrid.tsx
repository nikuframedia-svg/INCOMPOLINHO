/**
 * MachineStatusGrid — 5 machine status cards showing current state, SKU, and next op.
 * ISA-101: NEVER only color — always color + icon + text.
 */

import { useCallback, useMemo } from 'react';
import type { MachineState } from '@/components/Industrial/MachineStatusIndicator';
import type { Block, EngineData } from '@/domain/types/scheduling';
import { S0 } from '@/domain/types/scheduling';
import type { MachineLoad } from '@/hooks/useDayData';
import { useAndonActions, useAndonDowntimes } from '@/stores/useAndonStore';
import { postMachineUp } from '../api/andonApi';
import type { MachineStatus } from './MachineCard';
import { MachineCard } from './MachineCard';
import './MachineStatusGrid.css';

interface MachineStatusGridProps {
  engine: EngineData;
  blocks: Block[];
  machineLoads: MachineLoad[];
  clientMap?: Record<string, string>;
}

function deriveMachineStatuses(
  engine: EngineData,
  blocks: Block[],
  machineLoads: MachineLoad[],
): MachineStatus[] {
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const todayStr = now.toISOString().slice(0, 10);

  return engine.machines.map((m) => {
    const ml = machineLoads.find((x) => x.machineId === m.id);
    const mBlocks = ml?.blocks ?? blocks.filter((b) => b.machineId === m.id);
    const utilization = ml?.utilization ?? 0;

    const isLive = engine.dates[0] === todayStr && nowMin >= S0;

    let currentBlock: Block | null = null;
    let nextBlock: Block | null = null;
    let state: MachineState = 'stopped';

    if (isLive) {
      currentBlock = mBlocks.find((b) => b.startMin <= nowMin && b.endMin > nowMin) ?? null;
      nextBlock = mBlocks.find((b) => b.startMin > nowMin) ?? null;

      if (currentBlock) {
        if (
          currentBlock.setupS != null &&
          currentBlock.setupE != null &&
          nowMin >= currentBlock.setupS &&
          nowMin < currentBlock.setupE
        ) {
          state = 'transition';
        } else {
          state = 'running';
        }
      }
    } else {
      currentBlock = mBlocks[0] ?? null;
      nextBlock = mBlocks[1] ?? null;
      if (mBlocks.length > 0) state = 'running';
    }

    return { machineId: m.id, state, currentBlock, nextBlock, utilization };
  });
}

export function MachineStatusGrid({
  engine,
  blocks,
  machineLoads,
  clientMap,
}: MachineStatusGridProps) {
  const statuses = useMemo(
    () => deriveMachineStatuses(engine, blocks, machineLoads),
    [engine, blocks, machineLoads],
  );
  const downtimes = useAndonDowntimes();
  const { openDrawer, clearDowntime } = useAndonActions();

  const handleRecovery = useCallback(
    async (machineId: string) => {
      const dt = downtimes[machineId];
      if (!dt) return;
      await postMachineUp(machineId, dt.downEventId);
      clearDowntime(machineId);
    },
    [downtimes, clearDowntime],
  );

  return (
    <div className="msg" data-testid="machine-status-grid">
      {statuses.map((s) => (
        <MachineCard
          key={s.machineId}
          status={s}
          downtime={downtimes[s.machineId] ?? null}
          onAndonPress={openDrawer}
          onRecovery={handleRecovery}
          clientMap={clientMap}
        />
      ))}
    </div>
  );
}
