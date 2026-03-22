/**
 * AutoReplanCard — Auto-replan controls + AR strategy actions display.
 */
import { Check, ChevronDown, ChevronRight, Undo2, Zap } from 'lucide-react';
import { C } from '@/theme/color-bridge';
import { Card, Pill, Tag } from '../atoms';
import { ArActionItem } from './ArActionItem';
import type { AutoReplanCardProps } from './types';

export function AutoReplanCard({
  wdi,
  dates,
  dnames,
  nDays,
  tools,
  focusIds,
  arRunning,
  arResult,
  arActions,
  arSim,
  arSimId,
  arExclude,
  arDayFrom,
  arDayTo,
  arExpanded,
  arShowExclude,
  setArExclude,
  setArDayFrom,
  setArDayTo,
  setArExpanded,
  setArShowExclude,
  setArResult,
  runAutoReplan,
  handleArUndo,
  handleArAlt,
  handleArSimulate,
  handleArUndoAll,
  handleArApplyAll,
}: AutoReplanCardProps) {
  const selectStyle = {
    padding: '3px 6px',
    borderRadius: 4,
    border: `1px solid ${C.bd}`,
    background: C.bg,
    color: C.t1,
    fontSize: 12,
    fontFamily: 'inherit',
  } as const;

  return (
    <>
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
            <span style={{ fontSize: 12, color: C.t4, fontWeight: 400 }}>5 estratégias</span>
          </div>
          {arActions.length > 0 && <Tag color={C.ac}>{arActions.length} acções</Tag>}
        </div>

        {/* Date range */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 12, color: C.t3, minWidth: 56 }}>Horizonte:</span>
          <select
            value={arDayFrom}
            onChange={(e) => {
              setArDayFrom(Number(e.target.value));
              setArResult(null);
            }}
            style={selectStyle}
          >
            {wdi.map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 12, color: C.t4 }}>até</span>
          <select
            value={arDayTo}
            onChange={(e) => {
              setArDayTo(Number(e.target.value));
              setArResult(null);
            }}
            style={selectStyle}
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
              setArDayTo(wdi[wdi.length - 1] ?? nDays - 1);
              setArResult(null);
            }}
            style={{
              padding: '2px 8px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: 'transparent',
              color: C.t3,
              fontSize: 12,
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
              border: `1px solid ${arExclude.size > 0 ? `${C.yl}44` : C.bd}`,
              background: arExclude.size > 0 ? C.ylS : 'transparent',
              color: arExclude.size > 0 ? C.yl : C.t3,
              fontSize: 12,
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

      {/* AR Actions results */}
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
            {arActions.map((act) => (
              <ArActionItem
                key={act.decisionId}
                act={act}
                isExp={arExpanded === act.decisionId}
                isSim={arSimId === act.decisionId}
                arSim={arSim}
                setArExpanded={setArExpanded}
                handleArUndo={handleArUndo}
                handleArAlt={handleArAlt}
                handleArSimulate={handleArSimulate}
              />
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 12, fontSize: 12, color: C.t3 }}>
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
          <span style={{ fontSize: 12, fontWeight: 600, color: C.ac }}>
            Auto-replan concluído — sem acções necessárias
          </span>
        </div>
      )}
    </>
  );
}
