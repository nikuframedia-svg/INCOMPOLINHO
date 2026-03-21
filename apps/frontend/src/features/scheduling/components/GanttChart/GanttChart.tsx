import { AlertTriangle, Layers, Lock } from 'lucide-react';
import { useCallback, useRef } from 'react';
import type { Block, DayLoad, EngineData, OptResult, ScheduleValidationReport } from '../../../../lib/engine';
import { C, S0 } from '../../../../lib/engine';
import { useGanttDragDrop } from '../../hooks/useGanttDragDrop';
import { useGanttInteraction } from '../../hooks/useGanttInteraction';
import { Card, Pill, Tag, toolColor } from '../atoms';
import { BlockDetailCard } from './BlockDetailCard';
import { DeviationPanel } from './DeviationPanel';
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
    hov, selDay, selM, zoom, selOp, selBlock,
    dayB, dayBlkN, activeM, wdi, ppm, totalW, violationsByDay,
  } = gantt;
  const { setHov, setSelDay, setSelM, setZoom, setSelOp } = ganttActions;
  const handleDayChange = useCallback(
    (d: number) => { setSelDay(d); onDayChange?.(d); },
    [setSelDay, onDayChange],
  );
  const rowH = 54;
  const { drag, proposedMove, startDrag, endDrag, clearProposal } = useGanttDragDrop(activeM, rowH, ppm);
  const hours: number[] = [];
  for (let h = 7; h <= 24; h++) hours.push(h);
  if (data.thirdShift) for (let h = 25; h <= 31; h++) hours.push(h);

  // "Now" line position (only on today = day 0)
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
    <div role="region" aria-label="Plano de produção Gantt" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div
        style={{
          display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', flexWrap: 'wrap', gap: 6,
        }}
      >
        <div
          className="ne-day-strip"
          style={{ display: 'flex', gap: 3, overflowX: 'auto', flex: '1 1 0', minWidth: 0 }}
        >
          {wdi.map((i) => {
            const has = blocks.some((b) => b.dayIdx === i && b.type !== 'blocked');
            const vc = violationsByDay[i] ?? 0;
            return (
              <Pill key={i} active={selDay === i} color={C.ac} onClick={() => handleDayChange(i)} size="sm">
                <span style={{ opacity: has ? 1 : 0.4 }}>
                  {dnames[i]} {dates[i]}
                </span>
                {vc > 0 && (
                  <span style={{ fontSize: 12, fontWeight: 700, color: C.yl, marginLeft: 4, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                    <AlertTriangle size={8} strokeWidth={2.5} />
                    {vc}
                  </span>
                )}
              </Pill>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
          <Pill active={!selM} color={C.ac} onClick={() => setSelM(null)}>Todas</Pill>
          {machines
            .filter((m) => blocks.some((b) => b.dayIdx === selDay && b.machineId === m.id) || mSt[m.id] === 'down')
            .map((m) => {
              const isDown = mSt[m.id] === 'down';
              return (
                <Pill key={m.id} active={selM === m.id} color={isDown ? C.rd : C.ac} onClick={() => setSelM(selM === m.id ? null : m.id)}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: isDown ? C.rd : C.ac, display: 'inline-block', marginRight: 4 }} />
                  {m.id}
                </Pill>
              );
            })}
          <span style={{ width: 1, height: 16, background: C.bd, margin: '0 2px' }} />
          {[0.6, 1, 1.5, 2].map((z) => (
            <Pill key={z} active={zoom === z} color={C.bl} onClick={() => setZoom(z)}>{z}×</Pill>
          ))}
        </div>
      </div>

      <Card style={{ overflow: 'hidden', position: 'relative' }}>
        <div
          ref={containerRef}
          onMouseUp={handleMouseUp}
          style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 520, cursor: drag.isDragging ? 'grabbing' : undefined }}
        >
          <div style={{ minWidth: 100 + totalW, position: 'relative' }}>
            <TimelineHeader hours={hours} ppm={ppm} selDay={selDay} dnames={dnames} dates={dates} thirdShift={data.thirdShift} />
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
                  key={mc.id} mc={mc} mB={mB} mSt={mSt} cap={cap} data={data}
                  hours={hours} ppm={ppm} selDay={selDay} hov={hov} selOp={selOp}
                  tools={tools} thirdShift={data.thirdShift} setHov={setHov}
                  setSelOp={setSelOp} onDragStart={startDrag} isDragOver={dragOverMachine === mc.id}
                  blockClassifications={blockClassifications}
                />
              );
            })}
            {/* "Now" line — red dashed vertical */}
            {nowMin != null && nowMin >= S0 && (
              <div style={{
                position: 'absolute', left: 100 + (nowMin - S0) * ppm, top: 0, bottom: 0,
                borderLeft: '2px dashed var(--semantic-red)', zIndex: 15, pointerEvents: 'none',
              }}>
                <span style={{
                  position: 'absolute', top: 2, left: 4, fontSize: 12, fontWeight: 700,
                  color: 'var(--semantic-red)', whiteSpace: 'nowrap', background: `${C.s1}CC`, padding: '1px 4px', borderRadius: 3,
                }}>
                  AGORA — {String(Math.floor(nowMin / 60)).padStart(2, '0')}:{String(nowMin % 60).padStart(2, '0')}
                </span>
              </div>
            )}
          </div>
        </div>
        {/* BlockDetailCard — glass overlay */}
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

      {/* Legend */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', fontSize: 12, color: C.t3, padding: '4px 0' }}>
        {[...new Set(dayB.map((b) => b.toolId))].slice(0, 14).map((tid) => (
          <div key={tid} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: toolColor(tools, tid) }} />
            <span style={{ fontFamily: 'monospace' }}>{tid}</span>
          </div>
        ))}
        <span style={{ width: 1, height: 12, background: C.bd }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <div style={{ width: 14, height: 8, borderRadius: 2, background: `repeating-linear-gradient(45deg,${C.t3}40,${C.t3}40 2px,${C.t3}70 2px,${C.t3}70 4px)` }} />
          <span>Setup</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <div style={{ width: 14, height: 8, borderRadius: 2, border: `2px dashed ${C.rd}88` }} />
          <span>Congelado</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <Layers size={9} strokeWidth={1.5} style={{ color: C.t3 }} />
          <span>Co-produção</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <Lock size={9} strokeWidth={1.5} style={{ color: C.rd }} />
          <span>Frozen</span>
        </div>
        {dayBlkN > 0 && <Tag color={C.rd}>{dayBlkN} bloqueadas</Tag>}
      </div>

      {drag.isDragging && drag.block && (
        <div style={{
          position: 'fixed', left: drag.ghostX, top: drag.ghostY, pointerEvents: 'none', zIndex: 1000,
          width: Math.max((drag.block.endMin - drag.block.startMin) * ppm, 12), height: 17,
          background: `${C.ac}88`, borderRadius: 4, border: `2px solid ${C.ac}`,
          opacity: 0.8, display: 'flex', alignItems: 'center', paddingLeft: 4,
        }}>
          <span style={{ fontSize: 12, color: C.t1, fontWeight: 600 }}>{drag.block.toolId}</span>
        </div>
      )}

      {proposedMove && (
        <DeviationPanel
          move={proposedMove} blocks={blocks} currentMetrics={currentMetrics ?? null}
          onConfirm={handleDragConfirm} onCancel={clearProposal}
        />
      )}
    </div>
  );
}
