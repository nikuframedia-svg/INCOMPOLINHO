import { AlertTriangle, Layers, Sparkles } from 'lucide-react';
import React from 'react';
import type { Block, DayLoad, EngineData, ScheduleValidationReport } from '../../../../lib/engine';
import { C, DAY_CAP, S0, S1, T1 } from '../../../../lib/engine';
import { useGanttInteraction } from '../../hooks/useGanttInteraction';
import { Card, dot, fmtT, Pill, Tag, toolColor } from '../atoms';
import { ValidationPanel } from '../ValidationPanel';
import { OpDetailPanel } from './OpDetailPanel';

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
                <div
                  style={{
                    display: 'flex',
                    position: 'sticky',
                    top: 0,
                    zIndex: 10,
                    background: C.s1,
                    borderBottom: `1px solid ${C.bd}`,
                  }}
                >
                  <div
                    style={{
                      width: 100,
                      minWidth: 100,
                      padding: '8px 10px',
                      borderRight: `1px solid ${C.bd}`,
                      fontSize: 11,
                      fontWeight: 600,
                      color: C.t2,
                    }}
                  >
                    {dnames[selDay]} {dates[selDay]}
                  </div>
                  <div style={{ position: 'relative', height: 28, flex: 1 }}>
                    {hours.map((h) => {
                      const x = (h * 60 - S0) * ppm;
                      return (
                        <div
                          key={h}
                          style={{
                            position: 'absolute',
                            left: x,
                            top: 0,
                            height: '100%',
                            borderLeft: `1px solid ${C.bd}${h % 2 === 0 ? '' : '44'}`,
                          }}
                        >
                          <span
                            style={{
                              fontSize: 9,
                              color: h % 2 === 0 ? C.t3 : C.t4,
                              fontFamily: 'monospace',
                              position: 'absolute',
                              bottom: 3,
                              left: 4,
                            }}
                          >
                            {String(h).padStart(2, '0')}:00
                          </span>
                        </div>
                      );
                    })}
                    <div
                      style={{
                        position: 'absolute',
                        left: 0,
                        top: 0,
                        width: (T1 - S0) * ppm,
                        height: '100%',
                        background: `${C.ac}04`,
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        left: (T1 - S0) * ppm,
                        top: 0,
                        width: (S1 - T1) * ppm,
                        height: '100%',
                        background: `${C.bl}04`,
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        left: (T1 - S0) * ppm,
                        top: 0,
                        height: '100%',
                        borderLeft: `2px solid ${C.yl}66`,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 7,
                          color: C.yl,
                          position: 'absolute',
                          top: 2,
                          left: 4,
                          fontWeight: 600,
                        }}
                      >
                        T.Y
                      </span>
                    </div>
                    <span
                      style={{
                        position: 'absolute',
                        top: 2,
                        left: 4,
                        fontSize: 7,
                        color: C.ac,
                        fontWeight: 600,
                        opacity: 0.6,
                      }}
                    >
                      T.X
                    </span>
                  </div>
                </div>

                {activeM.length === 0 && dayB.length === 0 && (
                  <div
                    style={{ padding: '24px 16px', textAlign: 'center', color: C.t3, fontSize: 11 }}
                  >
                    Sem operações agendadas para {dnames[selDay]} {dates[selDay]}.
                  </div>
                )}
                {activeM.map((mc) => {
                  const mB = dayB.filter((b) => b.machineId === mc.id);
                  const isDown = mSt[mc.id] === 'down';
                  const rowH = Math.max(44, mB.length * 22 + 10);
                  const mC = cap[mc.id]?.[selDay];
                  const total = mC ? mC.prod + mC.setup : 0;
                  const u = total / DAY_CAP;
                  return (
                    <div
                      key={mc.id}
                      style={{
                        display: 'flex',
                        borderBottom: `1px solid ${C.bd}`,
                        minHeight: rowH,
                      }}
                    >
                      <div
                        style={{
                          width: 100,
                          minWidth: 100,
                          padding: '6px 10px',
                          borderRight: `1px solid ${C.bd}`,
                          background: C.s1,
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'center',
                          gap: 2,
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                          <span style={dot(isDown ? C.rd : C.ac, isDown)} />
                          <span
                            style={{
                              fontSize: 12,
                              fontWeight: 600,
                              color: isDown ? C.rd : C.t1,
                              fontFamily: 'monospace',
                            }}
                          >
                            {mc.id}
                          </span>
                        </div>
                        <div style={{ fontSize: 9, color: C.t3 }}>
                          {mc.area} · {mB.length} ops
                        </div>
                        {total > 0 && (
                          <div
                            style={{
                              fontSize: 10,
                              color: u > 1 ? C.rd : u > 0.85 ? C.yl : C.ac,
                              fontWeight: 600,
                            }}
                          >
                            {(u * 100).toFixed(0)}%
                          </div>
                        )}
                      </div>
                      <div
                        style={{
                          position: 'relative',
                          flex: 1,
                          height: rowH,
                          background: isDown ? C.rdS : 'transparent',
                        }}
                      >
                        {hours.map((h) => (
                          <div
                            key={h}
                            style={{
                              position: 'absolute',
                              left: (h * 60 - S0) * ppm,
                              top: 0,
                              bottom: 0,
                              borderLeft: `1px solid ${C.bd}22`,
                            }}
                          />
                        ))}
                        <div
                          style={{
                            position: 'absolute',
                            left: (T1 - S0) * ppm,
                            top: 0,
                            bottom: 0,
                            borderLeft: `2px solid ${C.yl}33`,
                          }}
                        />
                        {isDown && (
                          <div
                            style={{
                              position: 'absolute',
                              inset: 0,
                              background: `repeating-linear-gradient(45deg,transparent,transparent 8px,${C.rd}08 8px,${C.rd}08 16px)`,
                            }}
                          />
                        )}
                        {mB.map((b, bi) => {
                          const col = toolColor(tools, b.toolId);
                          const isH = hov === `${b.opId}-${selDay}`;
                          const isSel = selOp === b.opId;
                          const y = 5 + bi * 22;
                          return (
                            <React.Fragment key={`${b.opId}-${bi}`}>
                              {b.setupS != null && b.setupE != null && (
                                <div
                                  style={{
                                    position: 'absolute',
                                    left: (b.setupS - S0) * ppm,
                                    width: Math.max((b.setupE - b.setupS) * ppm, 4),
                                    top: y,
                                    height: 17,
                                    background: `repeating-linear-gradient(45deg,${col}40,${col}40 3px,${col}70 3px,${col}70 6px)`,
                                    borderRadius: '4px 0 0 4px',
                                    border: `1px solid ${col}66`,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                  }}
                                >
                                  <span style={{ fontSize: 8, color: col, fontWeight: 700 }}>
                                    SET
                                  </span>
                                </div>
                              )}
                              <div
                                onClick={() => setSelOp(selOp === b.opId ? null : b.opId)}
                                onMouseEnter={() => setHov(`${b.opId}-${selDay}`)}
                                onMouseLeave={() => setHov(null)}
                                style={{
                                  position: 'absolute',
                                  left: (b.startMin - S0) * ppm,
                                  width: Math.max((b.endMin - b.startMin) * ppm, 12),
                                  top: y,
                                  height: 17,
                                  background: isSel ? col : isH ? col : `${col}CC`,
                                  borderRadius: b.setupS != null ? '0 4px 4px 0' : 4,
                                  border: isSel
                                    ? `2px solid ${C.ac}`
                                    : b.moved
                                      ? `2px solid ${C.ac}`
                                      : `1px solid ${col}44`,
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  paddingLeft: 4,
                                  overflow: 'hidden',
                                  zIndex: isSel ? 25 : isH ? 20 : 1,
                                }}
                              >
                                <span
                                  style={{
                                    fontSize: 9,
                                    color: C.t1,
                                    fontWeight: 600,
                                    whiteSpace: 'nowrap',
                                    textShadow: '0 1px 3px #0009',
                                  }}
                                >
                                  {b.toolId}
                                </span>
                                {(b.endMin - b.startMin) * ppm > 70 && (
                                  <span style={{ fontSize: 8, color: C.t2, marginLeft: 5 }}>
                                    {b.qty.toLocaleString()}
                                  </span>
                                )}
                                {b.overflow && (
                                  <span
                                    style={{
                                      color: C.yl,
                                      marginLeft: 3,
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                    }}
                                  >
                                    <AlertTriangle size={8} strokeWidth={2} />
                                  </span>
                                )}
                                {b.isTwinProduction && (b.endMin - b.startMin) * ppm > 40 && (
                                  <span
                                    style={{
                                      color: '#fff9',
                                      marginLeft: 'auto',
                                      paddingRight: 3,
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                    }}
                                  >
                                    <Layers size={9} strokeWidth={2} />
                                  </span>
                                )}
                                {isH && (
                                  <div
                                    onClick={(e) => e.stopPropagation()}
                                    style={{
                                      position: 'absolute',
                                      bottom: 'calc(100% + 6px)',
                                      left: 0,
                                      background: C.s3,
                                      border: `1px solid ${col}44`,
                                      borderRadius: 8,
                                      padding: 10,
                                      zIndex: 30,
                                      width: 240,
                                    }}
                                  >
                                    <div style={{ fontSize: 11, fontWeight: 600, color: col }}>
                                      {b.toolId}
                                    </div>
                                    <div style={{ fontSize: 9, color: C.t2, marginBottom: 6 }}>
                                      {b.nm} · {b.sku}
                                    </div>
                                    <div
                                      style={{
                                        display: 'grid',
                                        gridTemplateColumns: '1fr 1fr',
                                        gap: '4px 12px',
                                        fontSize: 9,
                                      }}
                                    >
                                      {(
                                        [
                                          ['Qtd', `${b.qty.toLocaleString()}`],
                                          ['Tempo', `${(b.endMin - b.startMin).toFixed(0)}min`],
                                          ['Início', fmtT(b.startMin)],
                                          ['Fim', fmtT(b.endMin)],
                                          ['pcs/H', data.toolMap[b.toolId]?.pH],
                                          [
                                            'Setup',
                                            b.setupS != null && b.setupE != null
                                              ? `${b.setupE - b.setupS}min`
                                              : '—',
                                          ],
                                          ['Ops', b.operators],
                                          ['Máq', b.machineId],
                                        ] as [string, unknown][]
                                      ).map(([k, v], i) => (
                                        <div key={i} style={{ color: C.t3 }}>
                                          {k}{' '}
                                          <span style={{ color: C.t1, fontWeight: 600 }}>
                                            {String(v)}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                    {b.moved && (
                                      <div
                                        style={{
                                          fontSize: 9,
                                          color: C.ac,
                                          marginTop: 4,
                                          fontWeight: 600,
                                          display: 'flex',
                                          alignItems: 'center',
                                          gap: 3,
                                        }}
                                      >
                                        <Sparkles size={9} strokeWidth={1.5} /> Replaneado de{' '}
                                        {b.origM}
                                      </div>
                                    )}
                                    {b.isTwinProduction && b.outputs && (
                                      <div
                                        style={{
                                          borderTop: `1px solid ${col}33`,
                                          marginTop: 6,
                                          paddingTop: 6,
                                        }}
                                      >
                                        <div
                                          style={{
                                            fontSize: 9,
                                            color: col,
                                            fontWeight: 600,
                                            marginBottom: 3,
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 3,
                                          }}
                                        >
                                          <Layers size={9} strokeWidth={1.5} /> Co-Produção
                                        </div>
                                        {b.outputs.map((o, oi) => (
                                          <div key={oi} style={{ fontSize: 9, color: C.t3 }}>
                                            {o.sku}{' '}
                                            <span style={{ color: C.t1, fontWeight: 600 }}>
                                              {o.qty.toLocaleString()} pcs
                                            </span>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            </React.Fragment>
                          );
                        })}
                        {!isDown && total > 0 && (
                          <div
                            style={{
                              position: 'absolute',
                              bottom: 0,
                              left: 0,
                              right: 0,
                              height: 3,
                            }}
                          >
                            <div
                              style={{
                                height: '100%',
                                width: `${Math.min(u * 100, 100)}%`,
                                background: u > 1 ? C.rd : C.ac,
                                opacity: 0.25,
                                borderRadius: '0 2px 0 0',
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
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
