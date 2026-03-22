/**
 * ConsoleDay — Detailed day view at /console/day/:date
 *
 * Full timeline, KPIs, operation lists by status, and shift summary.
 */

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonCard, SkeletonTable } from '@/components/Common/SkeletonLoader';
import { KPICard } from '@/components/Industrial/KPICard';
import type { Block } from '@/domain/types/scheduling';
import { T1 } from '@/domain/types/scheduling';
import { useDayData } from '@/hooks/useDayData';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useUIStore } from '@/stores/useUIStore';
import { formatSetupTime, formatUtilization } from '@/utils/explicitText';
import { fmtMin } from '@/utils/format';
import { ConsoleDayOps } from '../components/ConsoleDayOps';
import { MachineTimeline } from '../components/MachineTimeline';
import { ShiftSummary } from '../components/ShiftSummary';
import './ConsoleDay.css';

function getNowMin(): number {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

function utilColor(u: number): string {
  if (u >= 0.95) return 'var(--semantic-red)';
  if (u >= 0.8) return 'var(--semantic-amber)';
  return 'var(--semantic-green)';
}

export function ConsoleDay() {
  const { date: rawDate } = useParams<{ date: string }>();
  const date = rawDate?.split('_').join('/');
  const navigate = useNavigate();

  const { engine, blocks: allBlocks } = useScheduleData();
  const { dayData, loading, error } = useDayData();
  const setSelectedDayIdx = useUIStore((s) => s.actions.setSelectedDayIdx);
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);

  // Resolve dayIdx from URL date
  const dayIdx = useMemo(() => {
    if (!engine || !date) return -1;
    return engine.dates.indexOf(date);
  }, [engine, date]);

  // Sync UIStore.selectedDayIdx with URL param
  useEffect(() => {
    if (dayIdx >= 0) setSelectedDayIdx(dayIdx);
  }, [dayIdx, setSelectedDayIdx]);

  // Navigation
  const prevDate = dayIdx > 0 ? engine?.dates[dayIdx - 1] : null;
  const nextDate = engine && dayIdx < engine.nDays - 1 ? engine.dates[dayIdx + 1] : null;

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

  // ── Operation lists by status ──
  const nowMin = useMemo(() => getNowMin(), []);
  const isToday = date === new Date().toISOString().slice(0, 10);

  const { completed, inProgress, pending } = useMemo(() => {
    if (!dayData) return { completed: [], inProgress: [], pending: [] };
    const blocks = dayData.blocks;

    if (!isToday) {
      return {
        completed: blocks.filter((b) => b.type === 'ok'),
        inProgress: [],
        pending: blocks.filter((b) => b.type !== 'ok'),
      };
    }

    const comp: Block[] = [];
    const prog: Block[] = [];
    const pend: Block[] = [];

    for (const b of blocks) {
      if (b.endMin <= nowMin) comp.push(b);
      else if (b.startMin <= nowMin && b.endMin > nowMin) prog.push(b);
      else pend.push(b);
    }
    return { completed: comp, inProgress: prog, pending: pend };
  }, [dayData, isToday, nowMin]);

  // Current shift
  const currentShift: 'A' | 'B' = getNowMin() < T1 ? 'A' : 'B';

  // Loading
  if (loading) {
    return (
      <div className="cday" data-testid="console-day-page">
        <div className="cday__nav">
          <h1 className="cday__title">Dia {date ?? '...'}</h1>
        </div>
        <div className="cday__kpis">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} lines={2} />
          ))}
        </div>
        <SkeletonTable rows={6} cols={5} />
      </div>
    );
  }

  // Error / invalid date
  if (error || !engine || !dayData || dayIdx < 0) {
    return (
      <div className="cday" data-testid="console-day-page">
        <div className="cday__nav">
          <button className="cday__nav-btn" onClick={() => navigate('/console')}>
            <ChevronLeft size={14} />
          </button>
          <h1 className="cday__title">Dia {date ?? '?'}</h1>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados para este dia"
          description={error ?? `Data "${date}" nao encontrada no horizonte de planeamento.`}
        />
      </div>
    );
  }

  return (
    <div className="cday" data-testid="console-day-page">
      {/* Header with navigation */}
      <div className="cday__nav">
        <button
          className="cday__nav-btn"
          disabled={!prevDate}
          onClick={() => prevDate && navigate(`/console/day/${prevDate.split('/').join('_')}`)}
        >
          <ChevronLeft size={14} />
        </button>
        <button
          className="cday__nav-btn"
          disabled={!nextDate}
          onClick={() => nextDate && navigate(`/console/day/${nextDate.split('/').join('_')}`)}
        >
          <ChevronRight size={14} />
        </button>
        <div>
          <h1 className="cday__title">
            {dayData.dayName} — {dayData.date}
          </h1>
          <span className="cday__subtitle">
            {dayData.blocks.length} blocos · {dayData.machineLoads.length} máquinas
          </span>
        </div>
        <span
          className={`cday__badge ${dayData.isWorkday ? 'cday__badge--workday' : 'cday__badge--weekend'}`}
        >
          {dayData.isWorkday ? 'Dia util' : 'Fim-de-semana'}
        </span>
      </div>

      {/* KPIs */}
      <div className="cday__kpis">
        <KPICard
          label="Pecas"
          value={dayData.totalPcs.toLocaleString()}
          unit="pcs"
          subtitle={dayData.totalPcs > 10000 ? 'Dia de alta carga' : 'Volume normal'}
        />
        <KPICard
          label="Produção"
          value={fmtMin(dayData.totalProdMin)}
          unit="min"
          subtitle={`${dayData.blocks.length} blocos em ${dayData.machineLoads.length} maq.`}
        />
        <KPICard
          label="Setup"
          value={fmtMin(dayData.totalSetupMin)}
          unit="min"
          subtitle={formatSetupTime(dayData.totalSetupMin, dayData.blocks.length).qualifier}
        />
        <KPICard
          label="Utilização"
          value={`${(dayData.factoryUtil * 100).toFixed(0)}`}
          unit="%"
          statusColor={utilColor(dayData.factoryUtil)}
          subtitle={
            formatUtilization(
              dayData.factoryUtil,
              dayData.machineLoads.filter((m) => m.utilization > 0).length,
              dayData.machineLoads.length,
            ).qualifier
          }
        />
      </div>

      {/* Timeline */}
      <MachineTimeline
        engine={dayData.engine}
        blocks={dayData.blocks}
        machineLoads={dayData.machineLoads}
        date={dayData.date}
        onBlockClick={handleBlockClick}
        onMachineClick={handleMachineClick}
      />

      {/* Operation lists */}
      {inProgress.length > 0 && (
        <ConsoleDayOps
          title="Em Curso"
          blocks={inProgress}
          defaultOpen
          onBlockClick={handleBlockClick}
        />
      )}

      <ConsoleDayOps
        title="Pendentes"
        blocks={pending}
        defaultOpen={pending.length > 0}
        onBlockClick={handleBlockClick}
      />

      <ConsoleDayOps
        title="Concluidas"
        blocks={completed}
        defaultOpen={false}
        onBlockClick={handleBlockClick}
      />

      {/* Shift Summary */}
      <ShiftSummary
        dayData={dayData}
        allBlocks={allBlocks}
        shift={currentShift}
        onNavigateToBlock={handleNavigateToBlock}
      />
    </div>
  );
}
