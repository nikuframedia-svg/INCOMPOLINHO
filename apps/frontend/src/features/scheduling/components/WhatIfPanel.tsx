import {
  AlertTriangle,
  ArrowRight,
  GitCommit,
  GitCompareArrows,
  History as HistoryIcon,
  Save,
  Star,
  X,
} from 'lucide-react';
import React from 'react';
import type { EngineData, MoveAction, OptResult } from '../../../lib/engine';
import {
  type buildResourceTimelines,
  C,
  genDecisions,
  opsByDayFromWorkforce,
} from '../../../lib/engine';
import type { PlanVersionParams } from '../../../stores/usePlanVersionStore';
import usePlanVersionStore from '../../../stores/usePlanVersionStore';
import useToastStore from '../../../stores/useToastStore';
import { gridDensityVars } from '../../../utils/gridDensity';
import { computePlanDiff } from '../../../utils/planDiff';
import { useWhatIf } from '../hooks/useWhatIf';
import { Card, dot, Metric, Pill, Tag, toolColor } from './atoms';
import { OBJECTIVE_PROFILES } from './constants';
import PlanComparePanel from './PlanComparePanel';

export default function WhatIfView({
  data,
  onApplyMoves,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
}: {
  data: EngineData;
  onApplyMoves?: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
}) {
  const { machines, tools, ops, dates, dnames, toolMap: TM, focusIds } = data;
  const { state: wi, actions: wiActions } = useWhatIf(
    data,
    OBJECTIVE_PROFILES,
    getResourceDownDays,
    replanTimelines,
  );
  const {
    sc,
    N,
    dispatchRule,
    objProfile,
    res,
    run,
    prog,
    editingDown,
    wdi: wdiWI,
    wiDownStartDay,
    wiDownEndDay,
    sel,
    showHistory,
    showCompare,
    diffPair,
    focusT,
    areaCaps,
    avOps,
    qv: qvWI,
  } = wi;
  const {
    setSc,
    setN,
    setDispatchRule,
    setObjProfile,
    setEditingDown,
    setWiDownStartDay,
    setWiDownEndDay,
    setSel,
    setShowHistory,
    setShowCompare,
    setDiffPair,
    setRes,
    optimize,
  } = wiActions;
  const versions = usePlanVersionStore((s) => s.versions);
  const currentId = usePlanVersionStore((s) => s.currentId);

  const rankColor = (i: number) => (i === 0 ? C.ac : i === 1 ? C.bl : C.pp);
  const rankLabel = (i: number) =>
    i === 0 ? '#1 MELHOR' : i === 1 ? '#2' : i === 2 ? '#3' : `#${i + 1}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>Otimização Monte Carlo</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {(() => {
              const n = machines.filter(
                (m) => getResourceDownDays('machine', m.id).size > 0,
              ).length;
              return n > 0 ? <Tag color={C.rd}>{n} máq DOWN</Tag> : null;
            })()}
            {(() => {
              const n = focusT.filter((t) => getResourceDownDays('tool', t.id).size > 0).length;
              return n > 0 ? <Tag color={C.yl}>{n} tool DOWN</Tag> : null;
            })()}
            <Tag color={C.pp}>N={N}</Tag>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 6 }}>
              Máquinas
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
              {focusIds.map((id) => {
                const downDays = getResourceDownDays('machine', id);
                return (
                  <Pill
                    key={id}
                    active={downDays.size > 0}
                    color={C.rd}
                    onClick={() => {
                      setEditingDown(
                        editingDown?.type === 'machine' && editingDown.id === id
                          ? null
                          : { type: 'machine', id },
                      );
                      setRes(null);
                    }}
                    size="sm"
                  >
                    <span style={dot(downDays.size > 0 ? C.rd : C.ac, downDays.size > 0)} />
                    {id}
                    {downDays.size > 0 ? ` ${downDays.size}d` : ''}
                  </Pill>
                );
              })}
            </div>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 6 }}>
              Ferramentas
            </div>
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 3,
                maxHeight: 60,
                overflowY: 'auto',
              }}
            >
              {focusT.map((t) => {
                const tDown = getResourceDownDays('tool', t.id);
                return (
                  <Pill
                    key={t.id}
                    active={tDown.size > 0}
                    color={C.rd}
                    onClick={() => {
                      setEditingDown(
                        editingDown?.type === 'tool' && editingDown.id === t.id
                          ? null
                          : { type: 'tool', id: t.id },
                      );
                      setRes(null);
                    }}
                    size="sm"
                  >
                    {t.id}
                    {tDown.size > 0 ? ` ${tDown.size}d` : ''}
                  </Pill>
                );
              })}
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
                        value={wiDownStartDay}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          setWiDownStartDay(v);
                          if (wiDownEndDay < v) setWiDownEndDay(v);
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
                        {wdiWI.map((i) => (
                          <option key={i} value={i}>
                            {dnames[i]} {dates[i]}
                          </option>
                        ))}
                      </select>
                      <span style={{ fontSize: 10, color: C.t4 }}>até</span>
                      <select
                        value={wiDownEndDay}
                        onChange={(e) => setWiDownEndDay(Number(e.target.value))}
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
                        {wdiWI
                          .filter((i) => i >= wiDownStartDay)
                          .map((i) => (
                            <option key={i} value={i}>
                              {dnames[i]} {dates[i]}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => {
                          const days: number[] = [];
                          for (let d = wiDownStartDay; d <= wiDownEndDay; d++) days.push(d);
                          setResourceDown(editingDown.type, editingDown.id, days);
                          setRes(null);
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
                    {currentDown.size > 0 && (
                      <div
                        style={{ display: 'flex', gap: 2, marginBottom: 8, alignItems: 'center' }}
                      >
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
                        onClick={() => {
                          setResourceDown(
                            editingDown.type,
                            editingDown.id,
                            dates.map((_: string, i: number) => i),
                          );
                          setRes(null);
                        }}
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
                        onClick={() => {
                          clearResourceDown(editingDown.type, editingDown.id);
                          setRes(null);
                        }}
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
          </div>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 5 }}>
              Operadores
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr 1fr',
                gap: 6,
                marginBottom: 10,
              }}
            >
              {[
                { l: 'PG1 Eq', k: 't1' as const },
                { l: 'PG1 Pool', k: 'p1' as const },
                { l: 'PG2 Eq', k: 't2' as const },
                { l: 'PG2 Pool', k: 'p2' as const },
              ].map((f) => (
                <div key={f.k}>
                  <div style={{ fontSize: 9, color: C.t4, marginBottom: 2 }}>{f.l}</div>
                  <input
                    type="number"
                    value={sc[f.k]}
                    onChange={(e) => {
                      setSc((p) => ({ ...p, [f.k]: parseInt(e.target.value) || 0 }));
                      setRes(null);
                    }}
                    style={{
                      width: '100%',
                      padding: 5,
                      borderRadius: 6,
                      border: `1px solid ${C.bd}`,
                      background: C.bg,
                      color: C.t1,
                      fontSize: 13,
                      fontFamily: 'monospace',
                      textAlign: 'center',
                    }}
                  />
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Iterações</div>
              {[100, 300, 500, 1000].map((n) => (
                <Pill
                  key={n}
                  active={N === n}
                  color={C.pp}
                  onClick={() => {
                    setN(n);
                    setRes(null);
                  }}
                  size="sm"
                >
                  {n}
                </Pill>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Seed</div>
              <input
                type="number"
                value={sc.seed}
                onChange={(e) => {
                  setSc((p) => ({ ...p, seed: parseInt(e.target.value) || 0 }));
                  setRes(null);
                }}
                style={{
                  width: 80,
                  padding: 4,
                  borderRadius: 6,
                  border: `1px solid ${C.bd}`,
                  background: C.bg,
                  color: C.t1,
                  fontSize: 11,
                  fontFamily: 'monospace',
                  textAlign: 'center',
                }}
              />
              <div style={{ fontSize: 8, color: C.t4 }}>Mesma seed = resultados reprodutiveis</div>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Heurística</div>
              {(['EDD', 'CR', 'WSPT', 'SPT'] as const).map((r) => (
                <Pill
                  key={r}
                  active={dispatchRule === r}
                  color={C.bl}
                  onClick={() => {
                    setDispatchRule(r);
                    setRes(null);
                  }}
                  size="sm"
                >
                  {r}
                </Pill>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Objectivo</div>
              {OBJECTIVE_PROFILES.map((p) => (
                <Pill
                  key={p.id}
                  active={objProfile === p.id}
                  color={C.ac}
                  onClick={() => {
                    setObjProfile(p.id);
                    setRes(null);
                  }}
                  size="sm"
                >
                  {p.label}
                </Pill>
              ))}
            </div>
            <button
              onClick={optimize}
              disabled={run}
              style={{
                width: '100%',
                padding: 12,
                borderRadius: 8,
                border: 'none',
                cursor: run ? 'wait' : 'pointer',
                background: run ? C.s3 : C.ac,
                color: run ? C.t3 : C.bg,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: 'inherit',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {run && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${prog}%`,
                    background: C.w + '15',
                    transition: 'width .1s',
                  }}
                />
              )}
              <span style={{ position: 'relative' }}>
                {run ? `Otimizando ${prog}%` : 'OTIMIZAR — encontrar top 3 planos'}
              </span>
            </button>
          </div>
        </div>
      </Card>

      {!res && !run && (
        <Card style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 15, marginBottom: 6, color: C.ac }}>OPTIMIZE</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t2 }}>
            Otimização de Planeamento
          </div>
          <div
            style={{
              fontSize: 10,
              color: C.t4,
              marginTop: 4,
              maxWidth: 400,
              margin: '4px auto 0',
              lineHeight: 1.6,
            }}
          >
            O motor explora {N} configurações de escalonamento diferentes — redistribuindo operações
            entre máquinas primárias e alternativas — e apresenta os 3 melhores planos otimizados
            por OTD, setups e capacidade.
          </div>
        </Card>
      )}

      {res && (
        <>
          <div style={{ display: 'flex', gap: 6 }}>
            {res.top3.map((s, i) => (
              <button
                key={i}
                onClick={() => setSel(i)}
                style={{
                  flex: 1,
                  padding: 12,
                  borderRadius: 8,
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontFamily: 'inherit',
                  background: sel === i ? C.s3 : C.s2,
                  border: `2px solid ${sel === i ? rankColor(i) : C.bd}`,
                  transition: 'all .15s',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: rankColor(i) }}>
                    {rankLabel(i)}
                  </span>
                  <span style={{ fontSize: 9, color: C.t4 }}>{s.label}</span>
                </div>
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 600,
                    color: s.otd < 95 ? C.rd : rankColor(i),
                    fontFamily: 'monospace',
                    lineHeight: 1,
                    marginTop: 4,
                  }}
                >
                  {s.otd.toFixed(1)}%
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: s.otdDelivery < 90 ? C.rd : C.t3,
                    marginTop: 2,
                    fontFamily: 'monospace',
                  }}
                >
                  OTD-D {s.otdDelivery.toFixed(1)}%
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 9, color: C.t3 }}>
                  <span>{s.setupCount} setups</span>
                  <span>{s.moves.length} moves</span>
                  <span style={{ color: C.yl }}>{s.tardinessDays.toFixed(1)}d tard.</span>
                </div>
              </button>
            ))}
          </div>

          {(qvWI.criticalCount > 0 || qvWI.highCount > 0) && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 12px',
                borderRadius: 6,
                background: qvWI.criticalCount > 0 ? C.rdS : `${C.yl}18`,
                borderLeft: `3px solid ${qvWI.criticalCount > 0 ? C.rd : C.yl}`,
              }}
            >
              <AlertTriangle
                size={13}
                style={{ color: qvWI.criticalCount > 0 ? C.rd : C.yl, flexShrink: 0 }}
              />
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: qvWI.criticalCount > 0 ? C.rd : C.yl,
                }}
              >
                {qvWI.criticalCount > 0
                  ? `${qvWI.criticalCount} conflito${qvWI.criticalCount > 1 ? 's' : ''} crítico${qvWI.criticalCount > 1 ? 's' : ''}`
                  : ''}
                {qvWI.criticalCount > 0 && qvWI.highCount > 0 ? ' · ' : ''}
                {qvWI.highCount > 0
                  ? `${qvWI.highCount} alerta${qvWI.highCount > 1 ? 's' : ''}`
                  : ''}
              </span>
              {qvWI.warnings.length > 0 && (
                <span style={{ fontSize: 9, color: C.t3, marginLeft: 'auto' }}>
                  {qvWI.warnings[0]}
                </span>
              )}
            </div>
          )}

          {onApplyMoves && res.top3[sel]?.moves.length > 0 && (
            <button
              onClick={() => {
                const mStNow = Object.fromEntries(
                  machines.map((m) => [
                    m.id,
                    getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
                  ]),
                );
                const tStNow = Object.fromEntries(
                  focusT
                    .filter((t) => getResourceDownDays('tool', t.id).size > 0)
                    .map((t) => [t.id, 'down']),
                );
                onApplyMoves(res.top3[sel].moves, { mSt: mStNow, tSt: tStNow });
              }}
              disabled={isSaving}
              style={{
                width: '100%',
                padding: 12,
                borderRadius: 8,
                border: 'none',
                cursor: isSaving ? 'wait' : 'pointer',
                background: isSaving ? C.s3 : C.ac,
                color: isSaving ? C.t3 : C.bg,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: 'inherit',
                opacity: isSaving ? 0.6 : 1,
              }}
            >
              {isSaving
                ? 'A guardar plano...'
                : `Aplicar Plano Selecionado (${res.top3[sel].moves.length} movimentos)`}
            </button>
          )}

          {/* WS2.3: Save/Commit/History buttons */}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={() => {
                const s = res.top3[sel];
                if (!s) return;
                const mStSave = Object.fromEntries(
                  machines.map((m) => [
                    m.id,
                    getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
                  ]),
                );
                const tStSave = Object.fromEntries(
                  focusT
                    .filter((t) => getResourceDownDays('tool', t.id).size > 0)
                    .map((t) => [t.id, 'down']),
                );
                const params: PlanVersionParams = {
                  machineStatus: mStSave,
                  toolStatus: tStSave,
                  areaCaps,
                  moves: s.moves,
                  seed: sc.seed,
                };
                const decs = genDecisions(
                  ops,
                  mStSave,
                  tStSave,
                  s.moves,
                  s.blocks,
                  machines,
                  TM,
                  focusIds,
                  tools,
                );
                const id = usePlanVersionStore.getState().savePlan(s as any, decs, params, s.label);
                useToastStore
                  .getState()
                  .addToast(`Versão guardada: ${s.label} (${id.slice(0, 8)})`, 'success', 4000);
              }}
              style={{
                flex: 1,
                padding: '8px 16px',
                borderRadius: 6,
                border: `1px solid ${C.bd}`,
                cursor: 'pointer',
                background: 'transparent',
                color: C.t1,
                fontSize: 12,
                fontWeight: 500,
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
              }}
            >
              <Save size={14} strokeWidth={1.5} />
              Guardar Versão
            </button>
            {versions.length > 0 && (
              <button
                onClick={() => {
                  const last = versions[versions.length - 1];
                  usePlanVersionStore.getState().commitPlan(last.id);
                  useToastStore
                    .getState()
                    .addToast(`Plano committed: ${last.label}`, 'success', 4000);
                }}
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  border: `1px solid ${C.acM}`,
                  cursor: 'pointer',
                  background: C.acS,
                  color: C.ac,
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: 'inherit',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <GitCommit size={14} strokeWidth={1.5} />
                Commit
              </button>
            )}
            <button
              onClick={() => setShowHistory((h) => !h)}
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                border: `1px solid ${showHistory ? C.acM : C.bd}`,
                cursor: 'pointer',
                background: showHistory ? C.acS : 'transparent',
                color: showHistory ? C.ac : C.t2,
                fontSize: 12,
                fontWeight: 500,
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <HistoryIcon size={14} strokeWidth={1.5} />
              {versions.length}
            </button>
            {versions.length >= 2 && (
              <button
                onClick={() => {
                  setShowCompare((c) => !c);
                  setShowHistory(false);
                }}
                style={{
                  padding: '8px 12px',
                  borderRadius: 6,
                  border: `1px solid ${showCompare ? C.blS : C.bd}`,
                  cursor: 'pointer',
                  background: showCompare ? C.blS : 'transparent',
                  color: showCompare ? C.bl : C.t2,
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: 'inherit',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <GitCompareArrows size={14} strokeWidth={1.5} />
                Comparar
              </button>
            )}
          </div>

          {/* WS2.3: Version History Panel */}
          {showHistory && versions.length > 0 && (
            <Card style={{ padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
                Histórico de Versões <Tag color={C.pp}>{versions.length}</Tag>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0, paddingLeft: 12 }}>
                {[...versions].reverse().map((v, i) => {
                  const isCurrent = v.id === currentId;
                  const isFirst = i === versions.length - 1;
                  return (
                    <div
                      key={v.id}
                      style={{ position: 'relative', paddingLeft: 20, paddingBottom: 16 }}
                    >
                      {/* Timeline connector */}
                      {i < versions.length - 1 && (
                        <div
                          style={{
                            position: 'absolute',
                            left: 3,
                            top: 10,
                            bottom: 0,
                            width: 1,
                            background: 'rgba(255,255,255,0.06)',
                          }}
                        />
                      )}
                      {/* Timeline dot */}
                      <div
                        style={{
                          position: 'absolute',
                          left: 0,
                          top: 2,
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          background: isCurrent ? C.ac : isFirst ? C.t4 : C.t3,
                        }}
                      />
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <button
                            onClick={() =>
                              usePlanVersionStore.getState().setFavorite(v.id, !v.isFavorite)
                            }
                            style={{
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                              padding: 0,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <Star
                              size={12}
                              strokeWidth={1.5}
                              fill={v.isFavorite ? C.yl : 'none'}
                              style={{ color: v.isFavorite ? C.yl : C.t4 }}
                            />
                          </button>
                          <span style={{ fontSize: 13, fontWeight: 500, color: C.t1 }}>
                            {v.label}
                          </span>
                          {v.branchLabel && (
                            <span
                              style={{
                                fontSize: 9,
                                fontWeight: 600,
                                color: C.pp,
                                background: C.ppS,
                                padding: '1px 6px',
                                borderRadius: 3,
                              }}
                            >
                              {v.branchLabel}
                            </span>
                          )}
                          {isCurrent && (
                            <span
                              style={{
                                padding: '2px 8px',
                                borderRadius: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                background: C.acS,
                                color: C.ac,
                                textTransform: 'uppercase',
                                letterSpacing: '0.04em',
                              }}
                            >
                              COMMITTED
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: 11, color: C.t3, fontFamily: 'var(--font-mono)' }}>
                          {v.id.slice(0, 8)}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: C.t3, marginTop: 2 }}>
                        {new Date(v.timestamp).toLocaleTimeString('pt-PT', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                        {' · '}OTD {v.kpis.otd.toFixed(1)}% · OTD-D {v.kpis.otdDelivery.toFixed(1)}%
                        · {v.kpis.setupCount} setups · tard {v.kpis.tardinessDays.toFixed(1)}d
                      </div>
                      <div style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
                        {!isCurrent && (
                          <button
                            onClick={() => usePlanVersionStore.getState().commitPlan(v.id)}
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              border: `1px solid ${C.bd}`,
                              cursor: 'pointer',
                              background: 'transparent',
                              color: C.t2,
                              fontSize: 10,
                              fontFamily: 'inherit',
                            }}
                          >
                            Commit
                          </button>
                        )}
                        {i < versions.length - 1 && (
                          <button
                            onClick={() => {
                              const prev = [...versions].reverse()[i + 1];
                              if (prev) setDiffPair([prev.id, v.id]);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              border: `1px solid ${C.bd}`,
                              cursor: 'pointer',
                              background: 'transparent',
                              color: C.t2,
                              fontSize: 10,
                              fontFamily: 'inherit',
                            }}
                          >
                            Diff
                          </button>
                        )}
                        <input
                          placeholder="branch..."
                          defaultValue={v.branchLabel ?? ''}
                          onBlur={(e) =>
                            usePlanVersionStore
                              .getState()
                              .setBranchLabel(v.id, e.target.value.trim())
                          }
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                          }}
                          style={{
                            marginLeft: 'auto',
                            width: 80,
                            padding: '2px 6px',
                            borderRadius: 4,
                            border: `1px solid ${C.bd}`,
                            background: 'transparent',
                            color: C.t3,
                            fontSize: 9,
                            fontFamily: 'inherit',
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              {/* Diff display */}
              {diffPair &&
                (() => {
                  const vA = usePlanVersionStore.getState().getVersion(diffPair[0]);
                  const vB = usePlanVersionStore.getState().getVersion(diffPair[1]);
                  if (!vA || !vB) return null;
                  const diff = computePlanDiff(vA, vB);
                  return (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 12,
                        background: C.bg,
                        borderRadius: 6,
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
                          {vA.label} → {vB.label}
                        </span>
                        <button
                          onClick={() => setDiffPair(null)}
                          style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            color: C.t3,
                            padding: 2,
                          }}
                        >
                          <X size={12} strokeWidth={1.5} />
                        </button>
                      </div>
                      <div style={{ fontSize: 11, color: C.t2, marginBottom: 8 }}>
                        {diff.summary}
                      </div>
                      <div
                        style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}
                      >
                        {[
                          {
                            l: 'OTD',
                            v: `${diff.kpiDelta.otd > 0 ? '+' : ''}${diff.kpiDelta.otd.toFixed(1)}%`,
                            c: diff.kpiDelta.otd >= 0 ? C.ac : C.rd,
                          },
                          {
                            l: 'Setups',
                            v: `${diff.kpiDelta.setupCount > 0 ? '+' : ''}${diff.kpiDelta.setupCount}`,
                            c: diff.kpiDelta.setupCount <= 0 ? C.ac : C.rd,
                          },
                          {
                            l: 'Tardiness',
                            v: `${diff.kpiDelta.tardinessDays > 0 ? '+' : ''}${diff.kpiDelta.tardinessDays.toFixed(1)}d`,
                            c: diff.kpiDelta.tardinessDays <= 0 ? C.ac : C.rd,
                          },
                        ].map((k, i) => (
                          <div key={i} style={{ textAlign: 'center' }}>
                            <div style={{ fontSize: 9, color: C.t4 }}>{k.l}</div>
                            <div
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                color: k.c,
                                fontFamily: 'monospace',
                              }}
                            >
                              {k.v}
                            </div>
                          </div>
                        ))}
                      </div>
                      {diff.moved.length > 0 && (
                        <div style={{ marginTop: 8, fontSize: 10, color: C.t3 }}>
                          {diff.moved.length} ops movidas · Churn: {diff.churn.toFixed(0)} min
                        </div>
                      )}
                    </div>
                  );
                })()}
            </Card>
          )}

          {showCompare && <PlanComparePanel data={data} />}

          {(() => {
            const s = res.top3[sel];
            if (!s) return null;
            const rc = rankColor(sel);
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
                  {[
                    {
                      l: 'OTD Produção',
                      v: `${s.otd.toFixed(1)}%`,
                      s: 'qty produzida',
                      c: s.otd < 95 ? C.rd : rc,
                    },
                    {
                      l: 'OTD Entrega',
                      v: `${s.otdDelivery.toFixed(1)}%`,
                      s: 'cumprimento datas',
                      c: s.otdDelivery < 90 ? C.rd : s.otdDelivery < 95 ? C.yl : rc,
                    },
                    {
                      l: 'Produção',
                      v: `${(s.produced / 1000).toFixed(0)}K`,
                      s: `de ${(s.totalDemand / 1000).toFixed(0)}K`,
                      c: rc,
                    },
                    {
                      l: 'Setups',
                      v: s.setupCount,
                      s: `T.X ${s.setupByShift.X} / T.Y ${s.setupByShift.Y}${s.setupByShift.Z ? ` / T.Z ${s.setupByShift.Z}` : ''}`,
                      c: s.setupCount > 20 ? C.yl : rc,
                    },
                    {
                      l: 'Tardiness',
                      v: `${s.tardinessDays.toFixed(1)}d`,
                      s: 'atraso acumulado',
                      c: s.tardinessDays > 0 ? C.rd : rc,
                    },
                  ].map((k, i) => (
                    <Card key={i}>
                      <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
                    </Card>
                  ))}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 10 }}>
                  <Card style={{ padding: 14 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                      Movimentos <Tag color={rc}>{s.moves.length}</Tag>
                    </div>
                    {s.moves.length === 0 ? (
                      <div style={{ fontSize: 10, color: C.t4, padding: 12, textAlign: 'center' }}>
                        Sem movimentos — plano original
                      </div>
                    ) : (
                      s.moves.map((mv, i) => {
                        const op = ops.find((o) => o.id === mv.opId);
                        return (
                          <div
                            key={i}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                              padding: '5px 0',
                              borderBottom: i < s.moves.length - 1 ? `1px solid ${C.bd}` : 'none',
                            }}
                          >
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                color: toolColor(tools, op?.t || ''),
                                fontFamily: 'monospace',
                                minWidth: 52,
                              }}
                            >
                              {op?.t}
                            </span>
                            <span
                              style={{
                                fontSize: 10,
                                color: C.rd,
                                fontFamily: 'monospace',
                                textDecoration: 'line-through',
                              }}
                            >
                              {op?.m}
                            </span>
                            <span
                              style={{
                                color: rc,
                                fontWeight: 600,
                                display: 'inline-flex',
                                alignItems: 'center',
                              }}
                            >
                              <ArrowRight size={12} strokeWidth={1.5} />
                            </span>
                            <span
                              style={{
                                fontSize: 10,
                                color: rc,
                                fontFamily: 'monospace',
                                fontWeight: 600,
                              }}
                            >
                              {mv.toM}
                            </span>
                            <span
                              style={{
                                flex: 1,
                                fontSize: 9,
                                color: C.t3,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {op?.nm}
                            </span>
                          </div>
                        );
                      })
                    )}
                    {res.moveable.length > 0 && (
                      <div
                        style={{
                          fontSize: 9,
                          color: C.t4,
                          marginTop: 6,
                          padding: '6px 0',
                          borderTop: `1px solid ${C.bd}`,
                        }}
                      >
                        {res.moveable.length} operações movíveis ·{' '}
                        {
                          res.moveable.filter((m) => s.moves.find((mv) => mv.opId === m.opId))
                            .length
                        }{' '}
                        movidas
                      </div>
                    )}
                  </Card>

                  <Card style={{ padding: 14, overflow: 'auto' }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                      Capacidade por Máquina
                    </div>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: `80px repeat(${data.nDays},1fr)`,
                        gap: 3,
                        ...gridDensityVars(data.nDays),
                      }}
                    >
                      <div />
                      {dates.map((_d, i) => (
                        <div key={i} style={{ textAlign: 'center', fontSize: 9, color: C.t4 }}>
                          {dnames[i]}
                        </div>
                      ))}
                      {machines
                        .filter((mc) => {
                          const cm = s.capByMachine[mc.id];
                          return cm && cm.days.some((d) => d.prod > 0 || d.setup > 0);
                        })
                        .map((mc) => {
                          const isD = getResourceDownDays('machine', mc.id).size > 0;
                          return (
                            <React.Fragment key={mc.id}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <span style={dot(isD ? C.rd : C.ac, isD)} />
                                <span
                                  style={{
                                    fontSize: 10,
                                    fontWeight: 600,
                                    color: isD ? C.rd : C.t1,
                                    fontFamily: 'monospace',
                                  }}
                                >
                                  {mc.id}
                                </span>
                              </div>
                              {s.capByMachine[mc.id].days.map((d, di) => {
                                const u = d.util;
                                const hCap = isD
                                  ? C.rdS
                                  : u === 0
                                    ? 'transparent'
                                    : u < 0.6
                                      ? rc + '18'
                                      : u < 0.85
                                        ? rc + '30'
                                        : u < 1
                                          ? C.yl + '35'
                                          : C.rd + '35';
                                return (
                                  <div
                                    key={di}
                                    style={{
                                      background: hCap,
                                      borderRadius: 4,
                                      padding: '3px 2px',
                                      textAlign: 'center',
                                      minHeight: 36,
                                    }}
                                  >
                                    {d.prod + d.setup > 0 ? (
                                      <>
                                        <div
                                          style={{
                                            fontSize: 11,
                                            fontWeight: 600,
                                            color: C.t1,
                                            fontFamily: 'monospace',
                                          }}
                                        >
                                          {(u * 100).toFixed(0)}%
                                        </div>
                                        <div style={{ fontSize: 8, color: C.t4 }}>
                                          {d.pcs > 0 ? `${(d.pcs / 1000).toFixed(0)}K` : ''}
                                        </div>
                                      </>
                                    ) : (
                                      <div style={{ fontSize: 10, color: C.t4 }}>—</div>
                                    )}
                                  </div>
                                );
                              })}
                            </React.Fragment>
                          );
                        })}
                    </div>
                  </Card>
                </div>

                <Card style={{ padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                    Operadores / Dia
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {opsByDayFromWorkforce(s.workforceDemand, data.nDays).map((d, i) => (
                      <div key={i} style={{ flex: 1, textAlign: 'center' }}>
                        <div style={{ fontSize: 9, color: C.t4, marginBottom: 4 }}>
                          {dnames[i]} {dates[i]}
                        </div>
                        <div
                          style={{
                            height: 50,
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'flex-end',
                            gap: 1,
                          }}
                        >
                          {d.pg1 > 0 && (
                            <div
                              style={{
                                height: `${Math.min((d.pg1 / avOps) * 50, 48)}px`,
                                background: C.ac + '55',
                                borderRadius: '3px 3px 0 0',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}
                            >
                              <span style={{ fontSize: 8, color: C.ac, fontWeight: 600 }}>
                                {d.pg1}
                              </span>
                            </div>
                          )}
                          {d.pg2 > 0 && (
                            <div
                              style={{
                                height: `${Math.min((d.pg2 / avOps) * 50, 48)}px`,
                                background: C.bl + '55',
                                borderRadius: '0 0 3px 3px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}
                            >
                              <span style={{ fontSize: 8, color: C.bl, fontWeight: 600 }}>
                                {d.pg2}
                              </span>
                            </div>
                          )}
                        </div>
                        <div
                          style={{
                            fontSize: 10,
                            fontWeight: 600,
                            color: d.total > avOps ? C.rd : rc,
                            marginTop: 2,
                          }}
                        >
                          {d.total}
                        </div>
                        {d.total > avOps && (
                          <div style={{ fontSize: 8, color: C.rd }}>+{d.total - avOps}</div>
                        )}
                      </div>
                    ))}
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'center',
                      gap: 12,
                      marginTop: 6,
                      fontSize: 9,
                      color: C.t3,
                    }}
                  >
                    <span>
                      <span
                        style={{
                          display: 'inline-block',
                          width: 8,
                          height: 8,
                          borderRadius: 2,
                          background: C.ac + '55',
                          marginRight: 3,
                        }}
                      />
                      PG1
                    </span>
                    <span>
                      <span
                        style={{
                          display: 'inline-block',
                          width: 8,
                          height: 8,
                          borderRadius: 2,
                          background: C.bl + '55',
                          marginRight: 3,
                        }}
                      />
                      PG2
                    </span>
                    <span>Disponíveis: {avOps}</span>
                  </div>
                </Card>

                <Card style={{ padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                    Comparação Cenários
                  </div>
                  <div
                    style={{ display: 'grid', gridTemplateColumns: '120px repeat(3,1fr)', gap: 3 }}
                  >
                    <div />
                    {res.top3.map((_, i) => (
                      <div key={i} style={{ textAlign: 'center', padding: 4 }}>
                        <span style={{ fontSize: 10, fontWeight: 600, color: rankColor(i) }}>
                          {rankLabel(i)}
                        </span>
                      </div>
                    ))}
                    {[
                      {
                        l: 'OTD Produção',
                        f: (s2: OptResult) => `${s2.otd.toFixed(1)}%`,
                        best: (s2: OptResult) => s2.otd,
                      },
                      {
                        l: 'OTD Entrega',
                        f: (s2: OptResult) => `${s2.otdDelivery.toFixed(1)}%`,
                        best: (s2: OptResult) => s2.otdDelivery,
                      },
                      {
                        l: 'Produção',
                        f: (s2: OptResult) => `${(s2.produced / 1000).toFixed(0)}K`,
                        best: (s2: OptResult) => s2.produced,
                      },
                      {
                        l: 'Peças Perdidas',
                        f: (s2: OptResult) =>
                          s2.lostPcs > 0 ? `${(s2.lostPcs / 1000).toFixed(1)}K` : '0',
                        best: (s2: OptResult) => -s2.lostPcs,
                      },
                      {
                        l: 'Setups',
                        f: (s2: OptResult) => s2.setupCount,
                        best: (s2: OptResult) => -s2.setupCount,
                      },
                      {
                        l: 'Setup Time',
                        f: (s2: OptResult) => `${Math.round(s2.setupMin)}min`,
                        best: (s2: OptResult) => -s2.setupMin,
                      },
                      {
                        l: 'Movimentos',
                        f: (s2: OptResult) => s2.moves.length,
                        best: (s2: OptResult) => -s2.moves.length,
                      },
                      {
                        l: 'Pico Operadores',
                        f: (s2: OptResult) => s2.peakOps,
                        best: (s2: OptResult) => -s2.peakOps,
                      },
                      {
                        l: 'Over Capacity',
                        f: (s2: OptResult) => s2.overflows,
                        best: (s2: OptResult) => -s2.overflows,
                      },
                      {
                        l: 'Score',
                        f: (s2: OptResult) => s2.score.toFixed(1),
                        best: (s2: OptResult) => s2.score,
                      },
                    ].map((row, ri) => (
                      <React.Fragment key={ri}>
                        <div
                          style={{ fontSize: 10, color: C.t3, padding: '4px 0', fontWeight: 500 }}
                        >
                          {row.l}
                        </div>
                        {res.top3.map((s2, ci) => {
                          const isBest = res.top3.every((s3) => row.best(s2) >= row.best(s3));
                          return (
                            <div
                              key={ci}
                              style={{
                                textAlign: 'center',
                                fontSize: 11,
                                fontWeight: isBest ? 800 : 500,
                                color: isBest ? rankColor(ci) : C.t2,
                                fontFamily: 'monospace',
                                padding: '4px 0',
                                background: ci === sel ? C.s3 : 'transparent',
                                borderRadius: 4,
                              }}
                            >
                              {String(row.f(s2))}
                            </div>
                          );
                        })}
                      </React.Fragment>
                    ))}
                  </div>
                </Card>
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}
