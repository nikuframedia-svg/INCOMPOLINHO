import type { Block, DayLoad, EngineData, ScheduleValidationReport } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { useGanttInteraction } from '../../hooks/useGanttInteraction';
import { Card, Pill, Tag, toolColor } from '../atoms';
import { ValidationPanel } from '../ValidationPanel';
import { GanttMachineRow } from './GanttMachineRow';
import { OpDetailPanel } from './OpDetailPanel';
import { TimelineHeader } from './TimelineHeader';

export function GanttView({
  blocks,
  mSt,
  cap,
  data,
  applyMove,
  undoMove,
  validation,
}: {
  blocks: Block[];
  mSt: Record<string, string>;
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  validation?: ScheduleValidationReport | null;
}) {
  const { machines, dates, dnames, tools } = data;
  const { state: gantt, actions: ganttActions } = useGanttInteraction(
    blocks,
    machines,
    mSt,
    data.workdays,
    validation,
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
  const hours: number[] = [];
  for (let h = 7; h <= 24; h++) hours.push(h);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {validation && (
        <ValidationPanel
          validation={validation}
          dnames={dnames}
          dates={dates}
          applyMove={applyMove}
        />
      )}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 6,
        }}
      >
        <div
          className="ne-day-strip"
          style={{ display: 'flex', gap: 3, overflowX: 'auto', flex: '1 1 0', minWidth: 0 }}
        >
          {wdi.map((i) => {
            const has = blocks.some((b) => b.dayIdx === i && b.type !== 'blocked');
            return (
              <Pill
                key={i}
                active={selDay === i}
                color={C.ac}
                onClick={() => setSelDay(i)}
                size="sm"
              >
                <span style={{ opacity: has ? 1 : 0.4 }}>
                  {dnames[i]} {dates[i]}
                </span>
                {violationsByDay[i] > 0 && (
                  <span
                    style={{
                      fontSize: 7,
                      fontWeight: 700,
                      color: C.t1,
                      background: C.rd,
                      borderRadius: '50%',
                      width: 14,
                      height: 14,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginLeft: 3,
                      flexShrink: 0,
                    }}
                  >
                    {violationsByDay[i]}
                  </span>
                )}
              </Pill>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
          <Pill active={!selM} color={C.ac} onClick={() => setSelM(null)}>
            Todas
          </Pill>
          {machines
            .filter(
              (m) =>
                blocks.some((b) => b.dayIdx === selDay && b.machineId === m.id) ||
                mSt[m.id] === 'down',
            )
            .map((m) => (
              <Pill
                key={m.id}
                active={selM === m.id}
                color={mSt[m.id] === 'down' ? C.rd : C.ac}
                onClick={() => setSelM(selM === m.id ? null : m.id)}
              >
                {m.id}
              </Pill>
            ))}
          <span style={{ width: 1, height: 16, background: C.bd, margin: '0 2px' }} />
          {[0.6, 1, 1.5, 2].map((z) => (
            <Pill key={z} active={zoom === z} color={C.bl} onClick={() => setZoom(z)}>
              {z}×
            </Pill>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Card style={{ overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 520 }}>
              <div style={{ minWidth: 100 + totalW, position: 'relative' }}>
                <TimelineHeader
                  hours={hours}
                  ppm={ppm}
                  selDay={selDay}
                  dnames={dnames}
                  dates={dates}
                />
                {activeM.length === 0 && dayB.length === 0 && (
                  <div
                    style={{ padding: '24px 16px', textAlign: 'center', color: C.t3, fontSize: 11 }}
                  >
                    Sem operações agendadas para {dnames[selDay]} {dates[selDay]}.
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
                      setHov={setHov}
                      setSelOp={setSelOp}
                    />
                  );
                })}
              </div>
            </div>
          </Card>
          <div
            style={{
              display: 'flex',
              gap: 4,
              flexWrap: 'wrap',
              justifyContent: 'center',
              fontSize: 9,
              color: C.t3,
            }}
          >
            {[...new Set(dayB.map((b) => b.toolId))].slice(0, 14).map((tid) => (
              <div key={tid} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: toolColor(tools, tid),
                  }}
                />
                <span style={{ fontFamily: 'monospace', fontSize: 9 }}>{tid}</span>
              </div>
            ))}
            {dayBlkN > 0 && <Tag color={C.rd}>{dayBlkN} bloqueadas</Tag>}
          </div>
        </div>
        {selBlock && (
          <OpDetailPanel
            block={selBlock}
            tool={data.toolMap[selBlock.toolId]}
            op={data.ops.find((o) => o.id === selBlock.opId)}
            dayLoad={cap[selBlock.machineId]?.[selDay]}
            dnames={data.dnames}
            selDay={selDay}
            machines={data.machines}
            mSt={mSt}
            tools={tools}
            onMove={applyMove}
            onUndo={undoMove}
            onClose={() => setSelOp(null)}
          />
        )}
      </div>
    </div>
  );
}
