/**
 * useConsolePageData — All derived state & callbacks for ConsolePage.
 *
 * Extracts memos, callbacks, and side-effects so ConsolePage stays
 * a pure composition component under 300 LOC.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { Block } from '@/domain/types/scheduling';
import { DAY_CAP } from '@/domain/types/scheduling';
import { useDayData } from '@/hooks/useDayData';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useAndonDowntimes } from '@/stores/useAndonStore';
import { useToastStore } from '@/stores/useToastStore';
import { useUIStore } from '@/stores/useUIStore';
import { chooseLayer } from '@/utils/replan-helpers';

export function useConsolePageData() {
  const { dayData, loading, error } = useDayData();
  const { engine, cap, blocks: allBlocks, metrics, validation, lateDeliveries } = useScheduleData();
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  const setSelectedDayIdx = useUIStore((s) => s.actions.setSelectedDayIdx);
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);

  // Daily factory utilization for all days (DaySelector dots)
  const dailyUtils = useMemo(() => {
    if (!engine || !cap) return [];
    return engine.dates.map((_, i) => {
      let totalUsed = 0;
      let totalCap = 0;
      engine.machines.forEach((m) => {
        const d = cap[m.id]?.[i];
        if (d) {
          totalUsed += d.prod + d.setup;
          totalCap += DAY_CAP;
        }
      });
      return totalCap > 0 ? totalUsed / totalCap : 0;
    });
  }, [engine, cap]);

  // Sparkline data: last 7 days of KPIs relative to selected day
  const sparklines = useMemo(() => {
    if (!engine || !cap || !dayData) return undefined;
    const idx = dayData.dayIdx;
    const pcs: number[] = [];
    const ops: number[] = [];
    const util: number[] = [];
    const setup: number[] = [];
    const alerts: number[] = [];

    for (let d = Math.max(0, idx - 6); d <= idx; d++) {
      let dPcs = 0,
        dOps = 0,
        dSetup = 0,
        dUsed = 0,
        dCap = 0;
      for (const m of engine.machines) {
        const load = cap[m.id]?.[d];
        if (load) {
          dPcs += load.pcs;
          dOps += load.ops;
          dSetup += load.setup;
          dUsed += load.prod + load.setup;
          dCap += DAY_CAP;
        }
      }
      pcs.push(dPcs);
      ops.push(dOps);
      util.push(dCap > 0 ? dUsed / dCap : 0);
      setup.push(dSetup);

      const dayViolations =
        validation?.violations.filter((v) => v.affectedOps.some((a) => a.dayIdx === d)).length ?? 0;
      alerts.push(dayViolations);
    }
    return { pcs, ops, util, setup, alerts, operators: [] };
  }, [engine, cap, dayData, validation]);

  // OTD from global metrics
  const otd = metrics?.otdDelivery;

  // ClientMap: opId → client name (for MachineCard context)
  const clientMap = useMemo(() => {
    if (!engine) return {};
    const m: Record<string, string> = {};
    for (const op of engine.ops) {
      if (op.cl) m[op.id] = op.clNm || op.cl;
    }
    return m;
  }, [engine]);

  // Feasibility score for this day (ok blocks / total blocks)
  const dayFeasibilityScore = useMemo(() => {
    if (!dayData || dayData.blocks.length === 0) return 1;
    const okCount = dayData.okBlocks.length;
    const total = dayData.blocks.length;
    return total > 0 ? okCount / total : 1;
  }, [dayData]);

  // StatusBanner derivation
  const bannerVariant = useMemo((): 'ok' | 'warning' | 'critical' => {
    if (!dayData) return 'ok';
    if (dayData.infeasibilities.length > 0) return 'critical';
    if (dayData.violations.length > 0 || dayData.overflowBlocks.length > 0) return 'warning';
    return 'ok';
  }, [dayData]);

  const bannerMessage = useMemo(() => {
    if (!dayData) return '';
    const alertCount = dayData.violations.length + dayData.infeasibilities.length;
    if (alertCount === 0) {
      return `Dia ${dayData.dayName} ${dayData.date} — ${dayData.okBlocks.length} operações escalonadas sem problemas.`;
    }
    return `Dia ${dayData.dayName} ${dayData.date} — ${alertCount} alerta(s): ${dayData.infeasibilities.length} inviável(eis), ${dayData.violations.length} violação(ões).`;
  }, [dayData]);

  // Interactions
  const handleDaySelect = useCallback(
    (idx: number) => {
      if (!engine) return;
      setSelectedDayIdx(idx);
      setFocus({ dayIdx: idx, day: engine.dates[idx] });
    },
    [engine, setSelectedDayIdx, setFocus],
  );

  const handleBlockClick = useCallback(
    (block: Block) => {
      openContextPanel({ type: 'tool', id: block.toolId });
      setFocus({ machine: block.machineId, toolId: block.toolId, dayIdx: block.dayIdx });
    },
    [openContextPanel, setFocus],
  );

  const handleMachineClick = useCallback(
    (machineId: string) => {
      openContextPanel({ type: 'machine', id: machineId });
      setFocus({ machine: machineId });
    },
    [openContextPanel, setFocus],
  );

  const handleNavigateToBlock = useCallback(
    (opId: string) => {
      const block = allBlocks.find((b) => b.opId === opId);
      if (block) {
        openContextPanel({ type: 'tool', id: block.toolId });
        setFocus({ machine: block.machineId, toolId: block.toolId, dayIdx: block.dayIdx });
      }
    },
    [allBlocks, openContextPanel, setFocus],
  );

  // ── Andon replan evaluation ──
  const downtimes = useAndonDowntimes();
  const addToast = useToastStore((s) => s.actions.addToast);
  const prevDowntimeCount = useRef(0);

  useEffect(() => {
    const keys = Object.keys(downtimes);
    if (keys.length <= prevDowntimeCount.current) {
      prevDowntimeCount.current = keys.length;
      return;
    }
    prevDowntimeCount.current = keys.length;

    const latest = downtimes[keys[keys.length - 1]];
    if (!latest) return;

    const delayMin = latest.estimatedMin ?? 120;
    const layer = chooseLayer(delayMin);

    if (layer === 1) {
      addToast(
        `${latest.machineId} parada. Atraso <30min — plano ajustado automaticamente.`,
        'info',
      );
    } else {
      addToast(
        `${latest.machineId} parada. Atraso estimado >30min — vai à página Scheduling para redistribuir carga.`,
        'warning',
        6000,
      );
    }
  }, [downtimes, addToast]);

  return {
    // Raw data
    dayData,
    loading,
    error,
    engine,
    allBlocks,
    lateDeliveries,
    panelOpen,
    downtimes,

    // Derived
    dailyUtils,
    sparklines,
    otd,
    clientMap,
    dayFeasibilityScore,
    bannerVariant,
    bannerMessage,

    // Handlers
    handleDaySelect,
    handleBlockClick,
    handleMachineClick,
    handleNavigateToBlock,
  };
}
