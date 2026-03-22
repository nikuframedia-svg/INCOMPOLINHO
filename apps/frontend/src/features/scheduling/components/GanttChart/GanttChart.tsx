import { useCallback, useRef } from 'react';
import type {
  Block,
  DayLoad,
  EngineData,
  OptResult,
  ScheduleValidationReport,
} from '@/domain/types/scheduling';
import { S0 } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { useGanttDragDrop } from '../../hooks/useGanttDragDrop';
import { useGanttInteraction } from '../../hooks/useGanttInteraction';
import { Card } from '../atoms';
import { BlockDetailCard } from './BlockDetailCard';
import { DeviationPanel } from './DeviationPanel';
import { GanttControls } from './GanttControls';
import { GanttLegend } from './GanttLegend';
import { GanttMachineRow } from './GanttMachineRow';
import { TimelineHeader } from './TimelineHeader';

export function GanttView({
  blocks,
  mSt,
  cap,
  data,
  applyMove,
  undoMove,
  validation,
  currentMetrics,
  onDayChange,
  blockClassifications,
}: {
  blocks: Block[];
  mSt: Record<string, string>;
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  validation?: ScheduleValidationReport | null;
  currentMetrics?: OptResult | null;
  onDayChange?: (dayIdx: number) => void;
  blockClassifications?: Map<string, Set<string>>;
}) {
  const { machines, dates, dnames, tools } = data;
  const containerRef = useRef<HTMLDivElement>(null);
  const { state: gantt, actions: ganttActions } = useGanttInteraction(
    blocks,
    machines,
    mSt,
    data.workdays,
    validation,
    data.thirdShift,
  );
  const {
    hov,
    selDay,
    selM,
    zoom,
    selOp,
    selBlock,
    dayB,
    dayBlkN,
    activeM,
    wdi,
    ppm,
    totalW,
    violationsByDay,
  } = gantt;
  const { setHov, setSelDay, setSelM, setZoom, setSelOp } = ganttActions;
  const handleDayChange = useCallback(
    (d: number) => {
      setSelDay(d);
      onDayChange?.(d);
    },
    [setSelDay, onDayChange],
  );
  const rowH = 54;
  const { drag, proposedMove, startDrag, endDrag, clearProposal } = useGanttDragDrop(
    activeM,
    rowH,
    ppm,
  );
  const hours: number[] = [];
  for (let h = 7; h <= 24; h++) hours.push(h);
  if (data.thirdShift) for (let h = 25; h <= 31; h++) hours.push(h);

  const nowMin = (() => {
    if (selDay !== 0) return null;
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  })();

  const dragOverMachine: string | null = (() => {
    if (!drag.isDragging || !containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    const relY = drag.ghostY + drag.offsetY - rect.top;
    const idx = Math.floor(relY / rowH);
    const m = activeM[Math.max(0, Math.min(idx, activeM.length - 1))];
    return m?.id ?? null;
  })();

  const handleMouseUp = useCallback(() => {
    endDrag(containerRef.current?.getBoundingClientRect() ?? null);
  }, [endDrag]);

  const handleDragConfirm = useCallback(() => {
    if (!proposedMove) return;
    applyMove(proposedMove.block.opId, proposedMove.toMachineId);
    clearProposal();
  }, [proposedMove, applyMove, clearProposal]);

  return (
    <div
      role="region"
      aria-label="Plano de produção Gantt"
      style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
    >
      <GanttControls
        wdi={wdi}
        selDay={selDay}
        selM={selM}
        zoom={zoom}
        dnames={dnames}
        dates={dates}
        blocks={blocks}
        machines={machines}
        mSt={mSt}
        violationsByDay={violationsByDay}
        onDayChange={handleDayChange}
        onSelM={setSelM}
        onZoom={setZoom}
      />

      <Card style={{ overflow: 'hidden', position: 'relative' }}>
        <div
          ref={containerRef}
          onMouseUp={handleMouseUp}
          style={{
            overflowX: 'auto',
            overflowY: 'auto',
            maxHeight: 520,
            cursor: drag.isDragging ? 'grabbing' : undefined,
          }}
        >
          <div style={{ minWidth: 100 + totalW, position: 'relative' }}>
            <TimelineHeader
              hours={hours}
              ppm={ppm}
              selDay={selDay}
              dnames={dnames}
              dates={dates}
              thirdShift={data.thirdShift}
            />
            {activeM.length === 0 && dayB.length === 0 && (
              <div style={{ padding: '24px 16px', textAlign: 'center', color: C.t3, fontSize: 12 }}>
                {blocks.length === 0
                  ? 'Sem blocos schedulados. Verifique se o ISOP foi carregado.'
                  : `Sem operações para ${dnames[selDay]} ${dates[selDay]}. Seleccione outro dia.`}
              </div>
            )}
            {activeM.map((mc) => {
              const mB = dayB.filter((b) => b.machineId === mc.id);
              return (
                <GanttMachineRow
                  key={mc.id}
                  mc={mc}
                  mB={mB}
                  mSt={mSt}
                  cap={cap}
                  data={data}
                  hours={hours}
                  ppm={ppm}
                  selDay={selDay}
                  hov={hov}
                  selOp={selOp}
                  tools={tools}
                  thirdShift={data.thirdShift}
                  setHov={setHov}
                  setSelOp={setSelOp}
                  onDragStart={startDrag}
                  isDragOver={dragOverMachine === mc.id}
                  blockClassifications={blockClassifications}
                />
              );
            })}
            {nowMin != null && nowMin >= S0 && (
              <div
                style={{
                  position: 'absolute',
                  left: 100 + (nowMin - S0) * ppm,
                  top: 0,
                  bottom: 0,
                  borderLeft: '2px dashed var(--semantic-red)',
                  zIndex: 15,
                  pointerEvents: 'none',
                }}
              >
                <span
                  style={{
                    position: 'absolute',
                    top: 2,
                    left: 4,
                    fontSize: 12,
                    fontWeight: 700,
                    color: 'var(--semantic-red)',
                    whiteSpace: 'nowrap',
                    background: `${C.s1}CC`,
                    padding: '1px 4px',
                    borderRadius: 3,
                  }}
                >
                  AGORA — {String(Math.floor(nowMin / 60)).padStart(2, '0')}:
                  {String(nowMin % 60).padStart(2, '0')}
                </span>
              </div>
            )}
          </div>
        </div>
        {selBlock && (
          <BlockDetailCard
            block={selBlock}
            tool={data.toolMap[selBlock.toolId]}
            mSt={mSt}
            tools={tools}
            onMove={applyMove}
            onUndo={undoMove}
            onClose={() => setSelOp(null)}
          />
        )}
      </Card>

      <GanttLegend dayB={dayB} dayBlkN={dayBlkN} tools={tools} />

      {drag.isDragging && drag.block && (
        <div
          style={{
            position: 'fixed',
            left: drag.ghostX,
            top: drag.ghostY,
            pointerEvents: 'none',
            zIndex: 1000,
            width: Math.max((drag.block.endMin - drag.block.startMin) * ppm, 12),
            height: 17,
            background: `${C.ac}88`,
            borderRadius: 4,
            border: `2px solid ${C.ac}`,
            opacity: 0.8,
            display: 'flex',
            alignItems: 'center',
            paddingLeft: 4,
          }}
        >
          <span style={{ fontSize: 12, color: C.t1, fontWeight: 600 }}>{drag.block.toolId}</span>
        </div>
      )}

      {proposedMove && (
        <DeviationPanel
          move={proposedMove}
          blocks={blocks}
          currentMetrics={currentMetrics ?? null}
          onConfirm={handleDragConfirm}
          onCancel={clearProposal}
        />
      )}
    </div>
  );
}
