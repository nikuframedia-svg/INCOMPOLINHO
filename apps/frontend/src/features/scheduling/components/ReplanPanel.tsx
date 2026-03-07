import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  Eye,
  Sparkles,
  Star,
  Undo2,
  X,
  Zap,
} from 'lucide-react';
import React from 'react';
import type { Block, DayLoad, EngineData, EOp, MoveAction, OptResult } from '../../../lib/engine';
import { type buildResourceTimelines, C, DAY_CAP } from '../../../lib/engine';
import { gridDensityVars } from '../../../utils/gridDensity';
import { useReplanControl } from '../hooks/useReplanControl';
import { Card, dot, Metric, Pill, Tag, toolColor } from './atoms';
import { OBJECTIVE_PROFILES } from './constants';

export default function ReplanView({
  mSt,
  tSt,
  moves,
  applyMove,
  undoMove,
  blocks,
  cap,
  data,
  onApplyAndSave,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
  rushOrders,
  setRushOrders,
  allOps,
  neMetrics,
}: {
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  toggleM?: (id: string) => void;
  toggleT?: (id: string) => void;
  moves: MoveAction[];
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  onApplyAndSave?: () => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >;
  allOps: EOp[];
  neMetrics: (OptResult & { blocks: Block[] }) | null;
}) {
  const { machines, tools, ops, dates, dnames, toolMap: TM, focusIds } = data;
  const { state: rpc, actions: rpcActions } = useReplanControl(
    data,
    blocks,
    allOps,
    mSt,
    tSt,
    moves,
    applyMove,
    replanTimelines,
    OBJECTIVE_PROFILES,
    setRushOrders,
  );
  const {
    xai,
    editingDown,
    arResult,
    arActions,
    arRunning,
    arSim,
    arSimId,
    arExclude,
    wdi,
    downStartDay,
    downEndDay,
    arDayFrom,
    arDayTo,
    arExpanded,
    arShowExclude,
    failures,
    failureImpacts,
    showFailureForm,
    ffResType,
    ffResId,
    ffSev,
    ffCap,
    ffStartDay,
    ffEndDay,
    ffDesc,
    cascRunning,
    optRunning,
    optResults,
    optProgress,
    optN,
    optProfile,
    optMoveable,
    roTool,
    roQty,
    roDeadline,
    blockCountByMachine,
    decs,
    qv,
  } = rpc;
  const {
    setXai,
    setEditingDown,
    setArExclude,
    setDownStartDay,
    setDownEndDay,
    setArDayFrom,
    setArDayTo,
    setArExpanded,
    setArShowExclude,
    setShowFailureForm,
    setFfResType,
    setFfResId,
    setFfSev,
    setFfCap,
    setFfStartDay,
    setFfEndDay,
    setFfDesc,
    setOptN,
    setOptProfile,
    setRoTool,
    setRoQty,
    setRoDeadline,
    setArResult,
    setOptResults,
    runAutoReplan,
    handleArUndo,
    handleArAlt,
    handleArSimulate,
    handleArUndoAll,
    handleArApplyAll,
    addFailure,
    removeFailure,
    runCascadingReplan,
    runOpt,
    applyOptResult,
    addRushOrder,
    removeRushOrder,
  } = rpcActions;
  const rp = decs.filter((d) => d.type === 'replan'),
    blk = decs.filter((d) => d.type === 'blocked');
  const lP = blk.reduce((a, d) => a + ((d.impact?.pcsLost as number) || 0), 0);
  const otd = neMetrics ? neMetrics.otdDelivery.toFixed(1) : '—';
  const sC = (s: string) => ({ critical: C.rd, high: C.yl, medium: C.bl, low: C.ac })[s] || C.t3;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {(qv.criticalCount > 0 || qv.highCount > 0) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 12px',
            borderRadius: 6,
            background: qv.criticalCount > 0 ? C.rdS : `${C.yl}18`,
            borderLeft: `3px solid ${qv.criticalCount > 0 ? C.rd : C.yl}`,
          }}
        >
          <AlertTriangle
            size={13}
            style={{ color: qv.criticalCount > 0 ? C.rd : C.yl, flexShrink: 0 }}
          />
          <span
            style={{ fontSize: 10, fontWeight: 600, color: qv.criticalCount > 0 ? C.rd : C.yl }}
          >
            {qv.criticalCount > 0
              ? `${qv.criticalCount} conflito${qv.criticalCount > 1 ? 's' : ''} crítico${qv.criticalCount > 1 ? 's' : ''}`
              : ''}
            {qv.criticalCount > 0 && qv.highCount > 0 ? ' · ' : ''}
            {qv.highCount > 0 ? `${qv.highCount} alerta${qv.highCount > 1 ? 's' : ''}` : ''}
          </span>
          {qv.warnings.length > 0 && (
            <span style={{ fontSize: 9, color: C.t3, marginLeft: 'auto' }}>{qv.warnings[0]}</span>
          )}
        </div>
      )}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>
            Replaneamento{' '}
            <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>Remove & Repair</span>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {moves.length > 0 && (
              <Pill color={C.rd} active onClick={() => moves.forEach((m) => undoMove(m.opId))}>
                <Undo2
                  size={10}
                  strokeWidth={1.5}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Todos ({moves.length})
              </Pill>
            )}
            {rp.length > 0 && (
              <Pill
                color={C.ac}
                active
                onClick={() =>
                  rp.forEach((d) => d.action && applyMove(d.action.opId, d.action.toM))
                }
              >
                <Zap
                  size={10}
                  strokeWidth={1.5}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Auto ({rp.length})
              </Pill>
            )}
            {moves.length > 0 && onApplyAndSave && (
              <button
                onClick={onApplyAndSave}
                disabled={isSaving}
                style={{
                  padding: '5px 14px',
                  borderRadius: 8,
                  border: 'none',
                  cursor: isSaving ? 'wait' : 'pointer',
                  background: C.ac,
                  color: C.bg,
                  fontSize: 10,
                  fontWeight: 600,
                  fontFamily: 'inherit',
                  opacity: isSaving ? 0.6 : 1,
                }}
              >
                {isSaving ? 'A guardar...' : `Aplicar & Guardar (${moves.length})`}
              </button>
            )}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 6 }}>
            Máquinas
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {machines.map((m) => {
              const isD = mSt[m.id] === 'down';
              const n = blockCountByMachine[m.id] ?? 0;
              const mDownDays = getResourceDownDays('machine', m.id);
              return (
                <button
                  key={m.id}
                  onClick={() => {
                    if (mDownDays.size > 0) {
                      // Quick restore: clear all down days and close panel
                      clearResourceDown('machine', m.id);
                      setEditingDown(null);
                    } else {
                      // Open/close day picker to set down periods
                      setEditingDown(
                        editingDown?.type === 'machine' && editingDown.id === m.id
                          ? null
                          : { type: 'machine', id: m.id },
                      );
                    }
                  }}
                  style={{
                    padding: '6px 10px',
                    borderRadius: 8,
                    cursor: 'pointer',
                    textAlign: 'center',
                    minWidth: 80,
                    background: isD
                      ? C.rdS
                      : editingDown?.type === 'machine' && editingDown.id === m.id
                        ? `${C.ac}12`
                        : 'transparent',
                    border: `1.5px solid ${isD ? C.rd + '44' : editingDown?.type === 'machine' && editingDown.id === m.id ? C.ac + '44' : C.bd}`,
                    fontFamily: 'inherit',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 4,
                    }}
                  >
                    <span style={dot(isD ? C.rd : C.ac, isD)} />
                    <span style={{ fontSize: 9, fontWeight: 600, color: isD ? C.rd : C.ac }}>
                      {mDownDays.size > 0 ? `DOWN ${mDownDays.size}d` : 'RUN'}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: isD ? C.rd : C.t1,
                      fontFamily: 'monospace',
                      marginTop: 2,
                    }}
                  >
                    {m.id}
                  </div>
                  <div style={{ fontSize: 9, color: C.t4 }}>
                    {m.area} · {n} ops
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 5 }}>
            Ferramentas
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
            {tools
              .filter(
                (t) =>
                  focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
              )
              .map((t) => {
                const tDownDays = getResourceDownDays('tool', t.id);
                return (
                  <Pill
                    key={t.id}
                    active={tSt[t.id] === 'down'}
                    color={C.rd}
                    onClick={() => {
                      if (tDownDays.size > 0) {
                        clearResourceDown('tool', t.id);
                        setEditingDown(null);
                      } else {
                        setEditingDown(
                          editingDown?.type === 'tool' && editingDown.id === t.id
                            ? null
                            : { type: 'tool', id: t.id },
                        );
                      }
                    }}
                    size="sm"
                  >
                    {t.id}
                    {tDownDays.size > 0 ? ` ${tDownDays.size}d` : ''}
                  </Pill>
                );
              })}
          </div>
        </div>

        {/* Day range picker for temporal down */}
        {editingDown &&
          (() => {
            const currentDown = getResourceDownDays(editingDown.type, editingDown.id);
            return (
              <div
                style={{
                  marginTop: 10,
                  padding: 10,
                  borderRadius: 8,
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${C.bd}`,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 8,
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>
                    Período DOWN:{' '}
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", color: C.rd }}>
                      {editingDown.id}
                    </span>
                    <span style={{ fontSize: 9, fontWeight: 400, color: C.t4, marginLeft: 6 }}>
                      ({editingDown.type === 'machine' ? 'máquina' : 'ferramenta'})
                    </span>
                  </span>
                  <button
                    onClick={() => setEditingDown(null)}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      color: C.t4,
                      padding: 2,
                    }}
                  >
                    <X size={12} />
                  </button>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 10, color: C.t3, minWidth: 30 }}>De:</span>
                  <select
                    value={downStartDay}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setDownStartDay(v);
                      if (downEndDay < v) setDownEndDay(v);
                    }}
                    style={{
                      padding: '3px 6px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.bg,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi.map((i) => (
                      <option key={i} value={i}>
                        {dnames[i]} {dates[i]}
                      </option>
                    ))}
                  </select>
                  <span style={{ fontSize: 10, color: C.t4 }}>até</span>
                  <select
                    value={downEndDay}
                    onChange={(e) => setDownEndDay(Number(e.target.value))}
                    style={{
                      padding: '3px 6px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.bg,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi
                      .filter((i) => i >= downStartDay)
                      .map((i) => (
                        <option key={i} value={i}>
                          {dnames[i]} {dates[i]}
                        </option>
                      ))}
                  </select>
                  <button
                    onClick={() => {
                      const days: number[] = [];
                      for (let d = downStartDay; d <= downEndDay; d++) days.push(d);
                      setResourceDown(editingDown.type, editingDown.id, days);
                    }}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: 'none',
                      background: C.rd,
                      color: C.t1,
                      fontSize: 9,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Aplicar
                  </button>
                </div>
                {/* Visual preview of which days are DOWN */}
                {currentDown.size > 0 && (
                  <div style={{ display: 'flex', gap: 2, marginBottom: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 9, color: C.t4, minWidth: 30 }}>Dias:</span>
                    {dates.map((_d: string, i: number) => (
                      <div
                        key={i}
                        style={{
                          width: 6,
                          height: 18,
                          borderRadius: 2,
                          background: currentDown.has(i) ? C.rd : `${C.bd}44`,
                        }}
                        title={`${dnames[i]} ${dates[i]}${currentDown.has(i) ? ' — DOWN' : ''}`}
                      />
                    ))}
                    <span style={{ fontSize: 9, color: C.rd, fontWeight: 600, marginLeft: 4 }}>
                      {currentDown.size}d
                    </span>
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    onClick={() =>
                      setResourceDown(
                        editingDown.type,
                        editingDown.id,
                        dates.map((_: string, i: number) => i),
                      )
                    }
                    style={{
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: `1px solid ${C.rd}44`,
                      background: C.rdS,
                      color: C.rd,
                      fontSize: 9,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      fontWeight: 600,
                    }}
                  >
                    Tudo DOWN
                  </button>
                  <button
                    onClick={() => clearResourceDown(editingDown.type, editingDown.id)}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: 'transparent',
                      color: C.t3,
                      fontSize: 9,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Limpar
                  </button>
                </div>
              </div>
            );
          })()}
      </Card>

      {/* ── Auto-Replan Panel ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            Auto-Replan{' '}
            <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>5 estratégias</span>
          </div>
          {arActions.length > 0 && <Tag color={C.ac}>{arActions.length} acções</Tag>}
        </div>

        {/* Date range */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 10, color: C.t3, minWidth: 56 }}>Horizonte:</span>
          <select
            value={arDayFrom}
            onChange={(e) => {
              setArDayFrom(Number(e.target.value));
              setArResult(null);
            }}
            style={{
              padding: '3px 6px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: C.bg,
              color: C.t1,
              fontSize: 10,
              fontFamily: 'inherit',
            }}
          >
            {wdi.map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 10, color: C.t4 }}>até</span>
          <select
            value={arDayTo}
            onChange={(e) => {
              setArDayTo(Number(e.target.value));
              setArResult(null);
            }}
            style={{
              padding: '3px 6px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: C.bg,
              color: C.t1,
              fontSize: 10,
              fontFamily: 'inherit',
            }}
          >
            {wdi.map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              setArDayFrom(wdi[0] ?? 0);
              setArDayTo(wdi[wdi.length - 1] ?? data.nDays - 1);
              setArResult(null);
            }}
            style={{
              padding: '2px 8px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: 'transparent',
              color: C.t3,
              fontSize: 9,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Tudo
          </button>
        </div>

        {/* Exclude tools */}
        <div style={{ marginBottom: 10 }}>
          <button
            onClick={() => setArShowExclude(!arShowExclude)}
            style={{
              padding: '3px 10px',
              borderRadius: 4,
              border: `1px solid ${arExclude.size > 0 ? C.yl + '44' : C.bd}`,
              background: arExclude.size > 0 ? C.ylS : 'transparent',
              color: arExclude.size > 0 ? C.yl : C.t3,
              fontSize: 10,
              cursor: 'pointer',
              fontFamily: 'inherit',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 3,
            }}
          >
            {arExclude.size > 0 ? `${arExclude.size} ferramentas excluídas` : 'Excluir ferramentas'}
            {arShowExclude ? (
              <ChevronDown size={10} strokeWidth={1.5} />
            ) : (
              <ChevronRight size={10} strokeWidth={1.5} />
            )}
          </button>
          {arShowExclude && (
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 3,
                marginTop: 6,
                maxHeight: 80,
                overflowY: 'auto',
              }}
            >
              {tools
                .filter(
                  (t) =>
                    focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                )
                .map((t) => (
                  <Pill
                    key={t.id}
                    active={arExclude.has(t.id)}
                    color={C.yl}
                    onClick={() => {
                      setArExclude((prev) => {
                        const n = new Set(prev);
                        if (n.has(t.id)) n.delete(t.id);
                        else n.add(t.id);
                        return n;
                      });
                      setArResult(null);
                    }}
                    size="sm"
                  >
                    {t.id}
                  </Pill>
                ))}
            </div>
          )}
        </div>

        {/* Run button */}
        <button
          onClick={runAutoReplan}
          disabled={arRunning}
          data-testid="run-auto-replan"
          style={{
            width: '100%',
            padding: 10,
            borderRadius: 6,
            border: 'none',
            background: arRunning ? C.s3 : C.ac,
            color: arRunning ? C.t3 : C.bg,
            fontSize: 12,
            fontWeight: 600,
            cursor: arRunning ? 'wait' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          <Zap
            size={12}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}
          />
          {arRunning ? 'A executar...' : 'Executar Auto-Replan'}
        </button>
      </Card>

      {/* ── Auto-Replan Actions ── */}
      {arResult && arActions.length > 0 && (
        <Card style={{ padding: 16 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 12,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
              Acções Auto-Replan <Tag color={C.ac}>{arActions.length}</Tag>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              <Pill color={C.ac} active onClick={handleArApplyAll}>
                <Check
                  size={10}
                  strokeWidth={2}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Aplicar Todas
              </Pill>
              <Pill color={C.rd} active onClick={handleArUndoAll}>
                <Undo2
                  size={10}
                  strokeWidth={1.5}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Desfazer Todas
              </Pill>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {arActions.map((act) => {
              const isExp = arExpanded === act.decisionId;
              const isSim = arSimId === act.decisionId;
              const stratColor: Record<string, string> = {
                ADVANCE_PRODUCTION: C.ac,
                MOVE_ALT_MACHINE: C.bl,
                SPLIT_OPERATION: C.pp,
                OVERTIME: C.yl,
                THIRD_SHIFT: C.cy,
              };
              const sc2 = stratColor[act.strategy] || C.t3;
              return (
                <div
                  key={act.decisionId}
                  style={{
                    padding: 12,
                    borderRadius: 6,
                    background: isSim ? `${C.bl}08` : C.bg,
                    border: `1px solid ${isSim ? C.bl + '33' : C.bd}`,
                    borderLeft: `3px solid ${sc2}`,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      marginBottom: 4,
                      flexWrap: 'wrap',
                    }}
                  >
                    <Tag color={sc2}>{act.strategy.replace(/_/g, ' ')}</Tag>
                    <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>
                      {act.summary}
                    </span>
                    {act.reversible && (
                      <span
                        style={{
                          fontSize: 8,
                          color: C.ac,
                          fontWeight: 600,
                          background: C.acS,
                          padding: '1px 4px',
                          borderRadius: 3,
                        }}
                      >
                        REVERSÍVEL
                      </span>
                    )}
                    <span
                      style={{ fontSize: 9, color: C.t4, fontFamily: "'JetBrains Mono',monospace" }}
                    >
                      {act.opId}
                    </span>
                  </div>
                  <div style={{ fontSize: 10, color: C.t3, marginBottom: 8 }}>{act.detail}</div>

                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {act.alternatives.length > 0 && (
                      <button
                        onClick={() => setArExpanded(isExp ? null : act.decisionId)}
                        style={{
                          padding: '3px 8px',
                          borderRadius: 4,
                          border: `1px solid ${C.pp}33`,
                          background: isExp ? C.ppS : 'transparent',
                          color: C.pp,
                          fontSize: 9,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 3,
                        }}
                      >
                        {isExp ? (
                          <ChevronDown size={9} strokeWidth={1.5} />
                        ) : (
                          <ChevronRight size={9} strokeWidth={1.5} />
                        )}
                        {act.alternatives.length} alt.
                      </button>
                    )}
                    <button
                      onClick={() => handleArUndo(act.decisionId)}
                      style={{
                        padding: '3px 8px',
                        borderRadius: 4,
                        border: `1px solid ${C.rd}33`,
                        background: 'transparent',
                        color: C.rd,
                        fontSize: 9,
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                      }}
                    >
                      <Undo2 size={9} strokeWidth={1.5} /> Desfazer
                    </button>
                    <button
                      onClick={() => handleArSimulate(act.decisionId)}
                      style={{
                        padding: '3px 8px',
                        borderRadius: 4,
                        border: `1px solid ${C.bl}33`,
                        background: isSim ? C.blS : 'transparent',
                        color: C.bl,
                        fontSize: 9,
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                      }}
                    >
                      <Eye size={9} strokeWidth={1.5} /> Simular
                    </button>
                  </div>

                  {/* Alternatives expand */}
                  {isExp && act.alternatives.length > 0 && (
                    <div style={{ marginTop: 8, padding: 8, background: C.s2, borderRadius: 4 }}>
                      {act.alternatives.map((alt, ai) => (
                        <div
                          key={ai}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '4px 0',
                            borderBottom:
                              ai < act.alternatives.length - 1 ? `1px solid ${C.bd}` : 'none',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: 10, color: C.t1 }}>{alt.description}</div>
                            <div style={{ fontSize: 9, color: C.t4 }}>
                              {alt.actionType.replace(/_/g, ' ')}
                            </div>
                          </div>
                          <button
                            onClick={() => handleArAlt(act.decisionId, alt)}
                            style={{
                              padding: '3px 8px',
                              borderRadius: 4,
                              border: 'none',
                              background: C.ac,
                              color: C.bg,
                              fontSize: 9,
                              fontWeight: 600,
                              cursor: 'pointer',
                              fontFamily: 'inherit',
                            }}
                          >
                            Aplicar
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Simulation preview */}
                  {isSim && arSim && (
                    <div
                      style={{
                        marginTop: 8,
                        padding: 8,
                        background: `${C.bl}08`,
                        borderRadius: 4,
                        border: `1px solid ${C.bl}22`,
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 600, color: C.bl, marginBottom: 4 }}>
                        <Eye
                          size={10}
                          strokeWidth={1.5}
                          style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }}
                        />
                        Simulação: sem esta acção
                      </div>
                      <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.t2 }}>
                        <span>
                          Overflow: {arSim.overflowBefore} → {arSim.overflowAfter}{' '}
                          <span
                            style={{
                              color:
                                arSim.overflowDelta > 0
                                  ? C.rd
                                  : arSim.overflowDelta < 0
                                    ? C.ac
                                    : C.t3,
                              fontWeight: 600,
                            }}
                          >
                            ({arSim.overflowDelta > 0 ? '+' : ''}
                            {arSim.overflowDelta})
                          </span>
                        </span>
                      </div>
                      {arSim.unresolved.length > 0 && (
                        <div style={{ marginTop: 4 }}>
                          <div style={{ fontSize: 9, color: C.rd, fontWeight: 600 }}>
                            {arSim.unresolved.length} não resolvido
                            {arSim.unresolved.length > 1 ? 's' : ''}
                          </div>
                          {arSim.unresolved.slice(0, 5).map((u, i) => (
                            <div
                              key={i}
                              style={{
                                fontSize: 9,
                                color: C.t3,
                                fontFamily: "'JetBrains Mono',monospace",
                              }}
                            >
                              {u.opId}: {u.reason} (deficit: {u.deficit})
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div style={{ display: 'flex', gap: 12, marginTop: 12, fontSize: 10, color: C.t3 }}>
            <span>{arResult.autoMoves.length} movimentos</span>
            <span>{arResult.autoAdvances?.length ?? 0} adiantamentos</span>
            <span>{arResult.decisions.length} decisões</span>
          </div>
        </Card>
      )}

      {arResult && arActions.length === 0 && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 6,
            background: C.acS,
            border: `1px solid ${C.ac}33`,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Check size={12} strokeWidth={2} style={{ color: C.ac }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: C.ac }}>
            Auto-replan concluído — sem acções necessárias
          </span>
        </div>
      )}

      {/* ── Failures / Breakdowns Panel ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: failures.length > 0 || showFailureForm ? 10 : 0,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            Avarias / Indisponibilidades{' '}
            {failures.length > 0 && <Tag color={C.rd}>{failures.length}</Tag>}
          </div>
          <button
            onClick={() => setShowFailureForm(!showFailureForm)}
            style={{
              padding: '4px 10px',
              borderRadius: 4,
              border: `1px solid ${C.rd}33`,
              background: showFailureForm ? C.rdS : 'transparent',
              color: C.rd,
              fontSize: 10,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {showFailureForm ? 'Cancelar' : '+ Registar Avaria'}
          </button>
        </div>

        {/* Registration form */}
        {showFailureForm && (
          <div
            style={{
              padding: 12,
              background: C.bg,
              borderRadius: 6,
              border: `1px solid ${C.bd}`,
              marginBottom: 10,
            }}
          >
            <div
              style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}
            >
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Tipo
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {(['machine', 'tool'] as const).map((t) => (
                    <Pill
                      key={t}
                      active={ffResType === t}
                      color={C.bl}
                      onClick={() => {
                        setFfResType(t);
                        setFfResId('');
                      }}
                      size="sm"
                    >
                      {t === 'machine' ? 'Máquina' : 'Ferramenta'}
                    </Pill>
                  ))}
                </div>
              </div>
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Recurso
                </div>
                <select
                  value={ffResId}
                  onChange={(e) => setFfResId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '4px 6px',
                    borderRadius: 4,
                    border: `1px solid ${C.bd}`,
                    background: C.s2,
                    color: C.t1,
                    fontSize: 10,
                    fontFamily: 'inherit',
                  }}
                >
                  <option value="">Selecionar...</option>
                  {ffResType === 'machine'
                    ? machines.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.id} ({m.area})
                        </option>
                      ))
                    : tools
                        .filter(
                          (t) =>
                            focusIds.includes(t.m) ||
                            (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                        )
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.id}
                          </option>
                        ))}
                </select>
              </div>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 10,
                marginBottom: 8,
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Severidade
                </div>
                <div style={{ display: 'flex', gap: 3 }}>
                  {(
                    [
                      ['total', C.rd],
                      ['partial', C.yl],
                      ['degraded', C.bl],
                    ] as const
                  ).map(([s, c]) => (
                    <Pill
                      key={s}
                      active={ffSev === s}
                      color={c}
                      onClick={() => setFfSev(s)}
                      size="sm"
                    >
                      {s === 'total' ? 'Total' : s === 'partial' ? 'Parcial' : 'Degradada'}
                    </Pill>
                  ))}
                </div>
              </div>
              {ffSev !== 'total' && (
                <div>
                  <div
                    style={{
                      fontSize: 9,
                      color: C.t4,
                      marginBottom: 3,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '.04em',
                    }}
                  >
                    Capacidade restante
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <input
                      type="number"
                      value={ffCap}
                      onChange={(e) => setFfCap(Math.max(0, Math.min(99, Number(e.target.value))))}
                      style={{
                        width: 50,
                        padding: '3px 6px',
                        borderRadius: 4,
                        border: `1px solid ${C.bd}`,
                        background: C.s2,
                        color: C.t1,
                        fontSize: 10,
                        fontFamily: "'JetBrains Mono',monospace",
                        textAlign: 'center',
                      }}
                    />
                    <span style={{ fontSize: 10, color: C.t3 }}>%</span>
                  </div>
                </div>
              )}
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Período
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <select
                    value={ffStartDay}
                    onChange={(e) => setFfStartDay(Number(e.target.value))}
                    style={{
                      padding: '3px 4px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.s2,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi.map((i) => (
                      <option key={i} value={i}>
                        {dnames[i]} {dates[i]}
                      </option>
                    ))}
                  </select>
                  <span style={{ fontSize: 9, color: C.t4 }}>—</span>
                  <select
                    value={ffEndDay}
                    onChange={(e) => setFfEndDay(Number(e.target.value))}
                    style={{
                      padding: '3px 4px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.s2,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi
                      .filter((i) => i >= ffStartDay)
                      .map((i) => (
                        <option key={i} value={i}>
                          {dnames[i]} {dates[i]}
                        </option>
                      ))}
                  </select>
                </div>
              </div>
            </div>
            <div style={{ marginBottom: 8 }}>
              <div
                style={{
                  fontSize: 9,
                  color: C.t4,
                  marginBottom: 3,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '.04em',
                }}
              >
                Descrição
              </div>
              <input
                type="text"
                value={ffDesc}
                onChange={(e) => setFfDesc(e.target.value)}
                placeholder="Ex: Manutenção preventiva"
                style={{
                  width: '100%',
                  padding: '4px 8px',
                  borderRadius: 4,
                  border: `1px solid ${C.bd}`,
                  background: C.s2,
                  color: C.t1,
                  fontSize: 10,
                  fontFamily: 'inherit',
                }}
              />
            </div>
            <button
              onClick={addFailure}
              disabled={!ffResId}
              style={{
                padding: '6px 16px',
                borderRadius: 4,
                border: 'none',
                background: ffResId ? C.rd : C.s3,
                color: ffResId ? C.t1 : C.t4,
                fontSize: 10,
                fontWeight: 600,
                cursor: ffResId ? 'pointer' : 'default',
                fontFamily: 'inherit',
              }}
            >
              Registar
            </button>
          </div>
        )}

        {/* Active failures list */}
        {failures.map((f, fi) => {
          const imp = failureImpacts[fi];
          return (
            <div
              key={f.id}
              style={{
                padding: 10,
                background: C.rdS,
                borderRadius: 6,
                border: `1px solid ${C.rd}22`,
                marginBottom: 6,
                borderLeft: `3px solid ${C.rd}`,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 4,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: C.t1,
                      fontFamily: "'JetBrains Mono',monospace",
                    }}
                  >
                    {f.resourceId}
                  </span>
                  <Tag
                    color={f.severity === 'total' ? C.rd : f.severity === 'partial' ? C.yl : C.bl}
                  >
                    {f.severity === 'total'
                      ? 'TOTAL'
                      : f.severity === 'partial'
                        ? `PARCIAL ${Math.round(f.capacityFactor * 100)}%`
                        : `DEGRADADA ${Math.round(f.capacityFactor * 100)}%`}
                  </Tag>
                  <span style={{ fontSize: 10, color: C.t3 }}>
                    {dnames[f.startDay]} {dates[f.startDay]}
                    {f.startDay !== f.endDay ? ` — ${dnames[f.endDay]} ${dates[f.endDay]}` : ''}
                  </span>
                </div>
                <button
                  onClick={() => removeFailure(f.id)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: C.t3,
                    cursor: 'pointer',
                    padding: '0 2px',
                  }}
                >
                  <X size={12} strokeWidth={2} />
                </button>
              </div>
              {f.description && (
                <div style={{ fontSize: 10, color: C.t3, marginBottom: 4 }}>{f.description}</div>
              )}
              {imp && imp.summary.totalBlocksAffected > 0 && (
                <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.t2 }}>
                  <span>
                    <span style={{ fontWeight: 600, color: C.rd }}>
                      {imp.summary.totalBlocksAffected}
                    </span>{' '}
                    blocos afectados
                  </span>
                  <span>
                    <span style={{ fontWeight: 600, color: C.rd }}>
                      {imp.summary.totalQtyAtRisk.toLocaleString()}
                    </span>{' '}
                    pcs em risco
                  </span>
                  <span>{imp.summary.blocksWithAlternative} c/ alternativa</span>
                  <span style={{ color: C.rd, fontWeight: 600 }}>
                    {imp.summary.blocksWithoutAlternative} s/ alternativa
                  </span>
                </div>
              )}
              {imp && imp.summary.totalBlocksAffected === 0 && (
                <div style={{ fontSize: 10, color: C.ac }}>Sem impacto no schedule actual</div>
              )}
            </div>
          );
        })}

        {/* Cascading replan button */}
        {failures.length > 0 && (
          <button
            onClick={runCascadingReplan}
            disabled={cascRunning}
            data-testid="cascading-replan"
            style={{
              width: '100%',
              padding: 8,
              borderRadius: 6,
              border: 'none',
              background: cascRunning ? C.s3 : C.rd,
              color: cascRunning ? C.t3 : C.t1,
              fontSize: 11,
              fontWeight: 600,
              cursor: cascRunning ? 'wait' : 'pointer',
              fontFamily: 'inherit',
              marginTop: 6,
            }}
          >
            {cascRunning ? 'A replanificar...' : `Replanificar com Avarias (${failures.length})`}
          </button>
        )}

        {failures.length === 0 && !showFailureForm && (
          <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
            Sem avarias registadas
          </div>
        )}
      </Card>

      {/* ── Optimization Panel (Phase 3) ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            <Sparkles
              size={12}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4, color: C.pp }}
            />
            Optimização{' '}
            <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>
              {optMoveable.length} ops movíveis
            </span>
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            marginBottom: 10,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Perfil
            </div>
            <div style={{ display: 'flex', gap: 3 }}>
              {OBJECTIVE_PROFILES.map((p) => (
                <Pill
                  key={p.id}
                  active={optProfile === p.id}
                  color={C.pp}
                  onClick={() => {
                    setOptProfile(p.id);
                    setOptResults([]);
                  }}
                  size="sm"
                >
                  {p.label}
                </Pill>
              ))}
            </div>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Iterações
            </div>
            <div style={{ display: 'flex', gap: 3 }}>
              {[100, 200, 500].map((n) => (
                <Pill
                  key={n}
                  active={optN === n}
                  color={C.bl}
                  onClick={() => {
                    setOptN(n);
                    setOptResults([]);
                  }}
                  size="sm"
                >
                  {n}
                </Pill>
              ))}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <button
            onClick={runOpt}
            disabled={optRunning}
            data-testid="run-optimization"
            style={{
              padding: '8px 20px',
              borderRadius: 6,
              border: 'none',
              background: optRunning ? C.s3 : C.pp,
              color: optRunning ? C.t3 : C.t1,
              fontSize: 11,
              fontWeight: 600,
              cursor: optRunning ? 'wait' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <Sparkles
              size={11}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}
            />
            {optRunning ? `A optimizar... ${Math.round(optProgress * 100)}%` : 'Otimizar'}
          </button>
        </div>

        {/* Moveable ops summary */}
        {optMoveable.length > 0 && !optResults.length && (
          <div style={{ maxHeight: 120, overflowY: 'auto', marginBottom: 6 }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '70px 60px 50px 50px 1fr',
                gap: '2px 8px',
                fontSize: 10,
              }}
            >
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Ferramenta</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Prim.</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Alt.</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Pcs</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Horas</div>
              {optMoveable.slice(0, 12).map((mo) => (
                <React.Fragment key={mo.opId}>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono',monospace",
                      color: toolColor(tools, mo.toolId),
                      fontWeight: 600,
                    }}
                  >
                    {mo.toolId}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t2 }}>
                    {mo.primaryM}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.ac }}>
                    {mo.altM}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t1 }}>
                    {mo.totalPcs.toLocaleString()}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t3 }}>
                    {mo.hrs.toFixed(1)}h
                  </div>
                </React.Fragment>
              ))}
            </div>
            {optMoveable.length > 12 && (
              <div style={{ fontSize: 9, color: C.t4, textAlign: 'center', marginTop: 4 }}>
                +{optMoveable.length - 12} mais
              </div>
            )}
          </div>
        )}

        {/* Optimization results */}
        {optResults.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {optResults.slice(0, 5).map((r, ri) => {
              return (
                <div
                  key={ri}
                  style={{
                    padding: 10,
                    borderRadius: 6,
                    background: ri === 0 ? `${C.pp}08` : C.bg,
                    border: `1px solid ${ri === 0 ? C.pp + '33' : C.bd}`,
                    borderLeft: `3px solid ${ri === 0 ? C.pp : C.t4}`,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      {ri === 0 && <Star size={12} strokeWidth={1.5} style={{ color: C.pp }} />}
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: ri === 0 ? C.pp : C.t1,
                          fontFamily: "'JetBrains Mono',monospace",
                        }}
                      >
                        #{ri + 1}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, fontSize: 10 }}>
                      <span style={{ color: C.t3 }}>
                        OTD{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: r.otd >= 95 ? C.ac : C.rd,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.otd.toFixed(1)}%
                        </span>
                      </span>
                      <span style={{ color: C.t3 }}>
                        Setups{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: C.t1,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.setupCount}
                        </span>
                      </span>
                      <span style={{ color: C.t3 }}>
                        Tard.{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: r.tardinessDays > 0 ? C.yl : C.ac,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.tardinessDays.toFixed(1)}d
                        </span>
                      </span>
                      <span style={{ color: C.t3 }}>
                        Moves{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: C.bl,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.moves.length}
                        </span>
                      </span>
                    </div>
                    {r.label && <span style={{ fontSize: 9, color: C.t4 }}>{r.label}</span>}
                  </div>
                  <button
                    onClick={() => applyOptResult(r)}
                    data-testid={`apply-opt-${ri}`}
                    style={{
                      padding: '4px 12px',
                      borderRadius: 4,
                      border: 'none',
                      background: ri === 0 ? C.pp : C.s3,
                      color: C.t1,
                      fontSize: 10,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Aplicar
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {optMoveable.length === 0 && (
          <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
            Sem operações movíveis (todas as ferramentas numa só máquina)
          </div>
        )}
      </Card>

      {/* ── Rush Orders Panel (Phase 4) ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: rushOrders.length > 0 ? 10 : 0,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            <Zap
              size={12}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4, color: C.yl }}
            />
            Encomendas Urgentes{' '}
            {rushOrders.length > 0 && <Tag color={C.yl}>{rushOrders.length}</Tag>}
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'flex-end',
            marginBottom: rushOrders.length > 0 ? 10 : 0,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Ferramenta
            </div>
            <select
              value={roTool}
              onChange={(e) => setRoTool(e.target.value)}
              style={{
                padding: '4px 6px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 10,
                fontFamily: 'inherit',
                minWidth: 100,
              }}
            >
              <option value="">Selecionar...</option>
              {tools
                .filter(
                  (t) =>
                    focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                )
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.id}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Qtd
            </div>
            <input
              type="number"
              value={roQty}
              onChange={(e) => setRoQty(Math.max(1, Number(e.target.value)))}
              style={{
                width: 70,
                padding: '4px 6px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 10,
                fontFamily: "'JetBrains Mono',monospace",
                textAlign: 'center',
              }}
            />
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Deadline
            </div>
            <select
              value={roDeadline}
              onChange={(e) => setRoDeadline(Number(e.target.value))}
              style={{
                padding: '4px 6px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 10,
                fontFamily: 'inherit',
              }}
            >
              {wdi.map((i) => (
                <option key={i} value={i}>
                  {dnames[i]} {dates[i]}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={addRushOrder}
            disabled={!roTool}
            style={{
              padding: '5px 14px',
              borderRadius: 4,
              border: 'none',
              background: roTool ? C.yl : C.s3,
              color: roTool ? C.bg : C.t4,
              fontSize: 10,
              fontWeight: 600,
              cursor: roTool ? 'pointer' : 'default',
              fontFamily: 'inherit',
            }}
          >
            + Adicionar
          </button>
        </div>

        {rushOrders.map((ro, i) => {
          const tool = TM[ro.toolId];
          const hrs = tool ? ro.qty / tool.pH : 0;
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 10px',
                background: `${C.yl}08`,
                borderRadius: 4,
                border: `1px solid ${C.yl}22`,
                borderLeft: `3px solid ${C.yl}`,
                marginBottom: 4,
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: toolColor(tools, ro.toolId),
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {ro.toolId}
              </span>
              <span style={{ fontSize: 10, color: C.t2 }}>{ro.sku}</span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: C.t1,
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {ro.qty.toLocaleString()} pcs
              </span>
              <span style={{ fontSize: 10, color: C.t3 }}>{hrs.toFixed(1)}h</span>
              <span style={{ fontSize: 10, color: C.yl, fontWeight: 600 }}>
                até {dnames[ro.deadline]} {dates[ro.deadline]}
              </span>
              <span style={{ flex: 1 }} />
              <button
                onClick={() => removeRushOrder(i)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: C.t3,
                  cursor: 'pointer',
                  padding: '0 2px',
                }}
              >
                <X size={12} strokeWidth={2} />
              </button>
            </div>
          );
        })}

        {rushOrders.length === 0 && (
          <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
            Sem encomendas urgentes
          </div>
        )}
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
        {[
          { l: 'OTD', v: `${otd}%`, c: parseFloat(otd) < 95 ? C.rd : C.ac },
          {
            l: 'Decisões',
            v: decs.length,
            s: `${rp.length} replaneáveis`,
            c: decs.length > 0 ? C.yl : C.ac,
          },
          { l: 'Aplicadas', v: moves.length, c: moves.length > 0 ? C.ac : C.t3 },
          { l: 'Bloqueadas', v: blk.length, c: blk.length > 0 ? C.rd : C.ac },
          {
            l: 'Perdidas',
            v: lP > 0 ? `${(lP / 1000).toFixed(0)}K` : '0',
            c: lP > 0 ? C.rd : C.ac,
          },
        ].map((k, i) => (
          <Card key={i}>
            <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
          </Card>
        ))}
      </div>

      <div
        style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 12, alignItems: 'start' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {moves.length > 0 && (
            <Card style={{ padding: 12, background: C.acS, borderColor: C.ac + '22' }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: C.ac, marginBottom: 4 }}>
                Aplicadas ({moves.length})
              </div>
              {moves.map((mv) => {
                const op = ops.find((o) => o.id === mv.opId);
                return (
                  <div
                    key={mv.opId}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        color: toolColor(tools, op?.t || ''),
                        fontFamily: 'monospace',
                      }}
                    >
                      {op?.t}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: C.rd,
                        textDecoration: 'line-through',
                        fontFamily: 'monospace',
                      }}
                    >
                      {TM[op?.t || '']?.m}
                    </span>
                    <span style={{ color: C.ac, display: 'inline-flex', alignItems: 'center' }}>
                      <ArrowRight size={12} strokeWidth={1.5} />
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: C.ac,
                        fontFamily: 'monospace',
                        fontWeight: 600,
                      }}
                    >
                      {mv.toM}
                    </span>
                    <span style={{ flex: 1, fontSize: 9, color: C.t3 }}>{op?.nm}</span>
                    <Pill color={C.rd} active onClick={() => undoMove(mv.opId)} size="sm">
                      <Undo2 size={9} strokeWidth={1.5} />
                    </Pill>
                  </div>
                );
              })}
            </Card>
          )}

          {decs.length === 0 && moves.length === 0 && (
            <Card style={{ padding: 40, textAlign: 'center' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.t3 }}>Sem ações pendentes</div>
              <div style={{ fontSize: 10, color: C.t4, marginTop: 4 }}>
                Marca máquinas/ferramentas DOWN para ativar
              </div>
            </Card>
          )}

          {decs.map((d) => {
            const imp = d.impact as Record<string, unknown> | null;
            const dLoad = imp?.dLoad as
              | Array<{ day: number; current: number; added: number; total: number; util: number }>
              | undefined;
            return (
              <Card key={d.id} style={{ padding: 14, borderLeft: `3px solid ${sC(d.severity)}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <Tag color={sC(d.severity)}>{d.severity}</Tag>
                  <Tag color={d.type === 'replan' ? C.ac : C.rd}>
                    {d.type === 'replan' ? 'REPLAN' : 'BLOQUEADA'}
                  </Tag>
                  <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{d.title}</span>
                </div>
                <div style={{ fontSize: 10, color: C.t3, marginBottom: 6 }}>{d.desc}</div>
                {}

                {d.type === 'replan' && imp && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                    {(
                      [
                        { l: 'De', v: imp.fromM, c: C.rd },
                        { l: 'Para', v: imp.toM, c: C.ac },
                        { l: 'Setup', v: `+${imp.setupMin}m`, c: C.pp },
                        {
                          l: 'Peças',
                          v:
                            (imp.pcs as number) > 999
                              ? `${((imp.pcs as number) / 1000).toFixed(1)}K`
                              : imp.pcs,
                          c: C.t1,
                        },
                        { l: 'Horas', v: `${imp.hrs}h` },
                        {
                          l: 'Pico',
                          v: `${imp.destPeak}%`,
                          c: parseInt(imp.destPeak as string) > 85 ? C.yl : C.ac,
                        },
                      ] as Array<{ l: string; v: unknown; c?: string }>
                    ).map((m, i) => (
                      <div
                        key={i}
                        style={{ background: C.bg, borderRadius: 6, padding: '4px 8px' }}
                      >
                        <div style={{ fontSize: 8, color: C.t4 }}>{m.l}</div>
                        <div
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: m.c || C.t1,
                            fontFamily: 'monospace',
                          }}
                        >
                          {String(m.v)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {!!imp?.stockRisk && (
                  <div
                    style={{
                      fontSize: 10,
                      color: C.yl,
                      fontWeight: 600,
                      marginBottom: 4,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 3,
                    }}
                  >
                    <AlertTriangle size={10} strokeWidth={1.5} /> STOCK ZERO — OTD em risco
                  </div>
                )}
                {!!imp?.sharedMP && (
                  <div style={{ fontSize: 10, color: C.cy, marginBottom: 4 }}>
                    MP partilhada — oportunidade agrupar
                  </div>
                )}

                {d.type === 'replan' && dLoad && (
                  <div style={{ display: 'flex', gap: 2, marginBottom: 6 }}>
                    {dLoad
                      .filter((dl) => dl.total > 0 || dl.added > 0)
                      .slice(0, 6)
                      .map((dl) => (
                        <div key={dl.day} style={{ flex: 1, textAlign: 'center' }}>
                          <div style={{ fontSize: 8, color: C.t4 }}>{dnames[dl.day]}</div>
                          <div
                            style={{
                              height: 24,
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'flex-end',
                              background: C.bg,
                              borderRadius: 3,
                              overflow: 'hidden',
                            }}
                          >
                            <div
                              style={{
                                height: `${Math.min((dl.current / DAY_CAP) * 100, 100)}%`,
                                background: C.bl + '44',
                                minHeight: dl.current > 0 ? 1 : 0,
                              }}
                            />
                            {dl.added > 0 && (
                              <div
                                style={{
                                  height: `${Math.min((dl.added / DAY_CAP) * 100, 50)}%`,
                                  background: C.ac,
                                  minHeight: 1,
                                }}
                              />
                            )}
                          </div>
                          <div
                            style={{
                              fontSize: 8,
                              color: dl.util > 1 ? C.rd : C.ac,
                              fontWeight: 600,
                            }}
                          >
                            {(dl.util * 100).toFixed(0)}%
                          </div>
                        </div>
                      ))}
                  </div>
                )}

                <div
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                >
                  <button
                    onClick={() => setXai(xai === d.id ? null : d.id)}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 6,
                      border: `1px solid ${C.pp}33`,
                      background: xai === d.id ? C.ppS : 'transparent',
                      color: C.pp,
                      fontSize: 10,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    {xai === d.id ? (
                      <ChevronDown
                        size={10}
                        strokeWidth={1.5}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />
                    ) : (
                      <ChevronRight
                        size={10}
                        strokeWidth={1.5}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />
                    )}{' '}
                    Raciocínio ({d.reasoning.length})
                  </button>
                  {d.type === 'replan' && d.action && (
                    <Pill
                      color={C.ac}
                      active
                      onClick={() => applyMove(d.action!.opId, d.action!.toM)}
                    >
                      <Check
                        size={10}
                        strokeWidth={2}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />{' '}
                      Aplicar{' '}
                      <ArrowRight
                        size={10}
                        strokeWidth={1.5}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />{' '}
                      {d.action.toM}
                    </Pill>
                  )}
                  {d.type === 'blocked' && <Tag color={C.rd}>MANUAL</Tag>}
                </div>
                {xai === d.id && (
                  <div style={{ marginTop: 8, padding: 10, background: C.bg, borderRadius: 6 }}>
                    {d.reasoning.map((r, i) => (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          gap: 6,
                          padding: '3px 0',
                          borderBottom: i < d.reasoning.length - 1 ? `1px solid ${C.bd}` : 'none',
                        }}
                      >
                        <span style={{ fontSize: 10, color: C.pp, fontWeight: 600, minWidth: 16 }}>
                          {i + 1}.
                        </span>
                        <span
                          style={{
                            fontSize: 10,
                            color: r.startsWith('→')
                              ? C.ac
                              : r.startsWith('⚠')
                                ? C.yl
                                : r.startsWith('✓')
                                  ? C.ac
                                  : C.t2,
                            lineHeight: 1.5,
                          }}
                        >
                          {r}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>Impacto Capacidade</div>
          {machines
            .filter((m) => {
              const d = mSt[m.id] === 'down';
              const h = blocks.some(
                (b) => (b.moved && b.machineId === m.id) || (b.moved && b.origM === m.id),
              );
              return d || h;
            })
            .slice(0, 6)
            .map((mc) => {
              const isD = mSt[mc.id] === 'down';
              const mc_c = cap[mc.id];
              return (
                <Card key={mc.id} style={{ padding: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                    <span style={dot(isD ? C.rd : C.ac, isD)} />
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: isD ? C.rd : C.t1,
                        fontFamily: 'monospace',
                      }}
                    >
                      {mc.id}
                    </span>
                    <Tag color={isD ? C.rd : C.ac}>{isD ? 'OFF' : 'ON'}</Tag>
                  </div>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: `repeat(${data.nDays},1fr)`,
                      gap: 2,
                      ...gridDensityVars(data.nDays),
                    }}
                  >
                    {dates.map((_, di) => {
                      const dc = mc_c?.[di] || { prod: 0, setup: 0 };
                      const tot = dc.prod + dc.setup;
                      const u = tot / DAY_CAP;
                      return (
                        <div key={di} style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: 8, color: C.t4 }}>{dnames[di]}</div>
                          <div
                            style={{
                              height: 32,
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'flex-end',
                              background: C.bg,
                              borderRadius: 3,
                              overflow: 'hidden',
                            }}
                          >
                            {dc.setup > 0 && (
                              <div
                                style={{
                                  height: `${Math.min((dc.setup / DAY_CAP) * 100, 30)}%`,
                                  background: C.pp + '66',
                                  minHeight: 1,
                                }}
                              />
                            )}
                            {dc.prod > 0 && (
                              <div
                                style={{
                                  height: `${Math.min((dc.prod / DAY_CAP) * 100, 100)}%`,
                                  background: isD ? C.rd + '44' : u > 1 ? C.rd + '66' : C.ac + '66',
                                  minHeight: 1,
                                }}
                              />
                            )}
                          </div>
                          {tot > 0 && (
                            <div
                              style={{ fontSize: 8, color: u > 1 ? C.rd : C.ac, fontWeight: 600 }}
                            >
                              {(u * 100).toFixed(0)}%
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </Card>
              );
            })}
          {Object.values(mSt).every((s) => s !== 'down') && moves.length === 0 && (
            <Card style={{ padding: 24, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: C.t4 }}>Marca DOWN para ver impacto</div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
