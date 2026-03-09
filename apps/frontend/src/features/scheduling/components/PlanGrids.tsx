import { ArrowRight, Check, Zap } from 'lucide-react';
import React from 'react';
import type { DayLoad, EngineData } from '../../../lib/engine';
import { C, DAY_CAP } from '../../../lib/engine';
import { gridDensityVars } from '../../../utils/gridDensity';
import { Card, dot } from './atoms';
import type { AutoReplanSummary } from './decision-constants';

export { TopBacklogs, VolumeChart } from './PlanGridsExtra';

export function QuickReplan({
  arRunning,
  arSummary,
  onRun,
  onSwitchToReplan,
}: {
  arRunning: boolean;
  arSummary: AutoReplanSummary | null;
  onRun: () => void;
  onSwitchToReplan?: () => void;
}) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Zap size={14} strokeWidth={1.5} style={{ color: C.ac }} />
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>Auto-Replan Rápido</div>
            <div style={{ fontSize: 9, color: C.t3 }}>
              Analisa operações e sugere movimentos de optimização
            </div>
          </div>
        </div>
        <button
          onClick={onRun}
          disabled={arRunning}
          data-testid="plan-quick-replan"
          style={{
            padding: '6px 16px',
            borderRadius: 6,
            border: 'none',
            background: arRunning ? C.s3 : C.ac,
            color: arRunning ? C.t3 : C.bg,
            fontSize: 11,
            fontWeight: 600,
            cursor: arRunning ? 'wait' : 'pointer',
            fontFamily: 'inherit',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <Zap size={11} strokeWidth={1.5} style={{ display: 'inline', verticalAlign: 'middle' }} />
          {arRunning ? 'A executar...' : 'Executar'}
        </button>
      </div>
      {arSummary && (
        <div
          style={{
            marginTop: 10,
            padding: '8px 12px',
            borderRadius: 6,
            background: arSummary.actions.length > 0 ? C.s1 : C.acS,
            border: `1px solid ${arSummary.actions.length > 0 ? C.bd : C.ac + '33'}`,
          }}
        >
          {arSummary.actions.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Check size={12} strokeWidth={2} style={{ color: C.ac }} />
              <span style={{ fontSize: 11, fontWeight: 600, color: C.ac }}>
                Plano óptimo — sem acções necessárias
              </span>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.t1, marginBottom: 4 }}>
                {arSummary.actions.length} acções encontradas · {arSummary.moveCount} movimentos
                {arSummary.unresolvedCount > 0 && (
                  <span style={{ color: C.rd, marginLeft: 6 }}>
                    {arSummary.unresolvedCount} não resolvidos
                  </span>
                )}
              </div>
              {arSummary.actions.slice(0, 3).map((act, ai) => (
                <div
                  key={ai}
                  style={{
                    fontSize: 10,
                    color: C.t2,
                    padding: '2px 0',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "'JetBrains Mono',monospace",
                      color: C.ac,
                      fontSize: 8,
                      padding: '1px 4px',
                      borderRadius: 3,
                      background: C.acS,
                    }}
                  >
                    {act.strategy.replace(/_/g, ' ')}
                  </span>
                  <span
                    style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {act.summary}
                  </span>
                </div>
              ))}
              {arSummary.actions.length > 3 && (
                <div style={{ fontSize: 9, color: C.t4, marginTop: 2 }}>
                  +{arSummary.actions.length - 3} mais...
                </div>
              )}
              {onSwitchToReplan && (
                <button
                  onClick={onSwitchToReplan}
                  style={{
                    marginTop: 8,
                    padding: '5px 14px',
                    borderRadius: 6,
                    border: `1px solid ${C.ac}44`,
                    background: C.acS,
                    color: C.ac,
                    fontSize: 10,
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <ArrowRight size={10} strokeWidth={1.5} />
                  Ver e aplicar no Replan
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export function CapacityGrid({
  machines,
  wdi,
  cap,
  mSt,
  dnames,
  dates,
  hC,
}: {
  machines: EngineData['machines'];
  wdi: number[];
  cap: Record<string, DayLoad[]>;
  mSt: Record<string, string>;
  dnames: string[];
  dates: string[];
  hC: (u: number) => string;
}) {
  return (
    <Card style={{ padding: 16, overflow: 'auto' }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 10 }}>
        Capacidade Máquina × Dia
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `100px repeat(${wdi.length},1fr)`,
          gap: 3,
          ...gridDensityVars(wdi.length),
        }}
      >
        <div />
        {wdi.map((i) => (
          <div key={i} style={{ textAlign: 'center', fontSize: 9, color: C.t3, fontWeight: 600 }}>
            {dnames[i]} <span style={{ color: C.t4 }}>{dates[i]}</span>
          </div>
        ))}
        {machines
          .filter(
            (m) =>
              Object.values(cap[m.id] || []).some((d: DayLoad) => d.prod > 0) ||
              mSt[m.id] === 'down',
          )
          .map((mc) => (
            <React.Fragment key={mc.id}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '2px 0' }}>
                <span style={dot(mSt[mc.id] === 'down' ? C.rd : C.ac, mSt[mc.id] === 'down')} />
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: mSt[mc.id] === 'down' ? C.rd : C.t1,
                    fontFamily: 'monospace',
                  }}
                >
                  {mc.id}
                </span>
                <span style={{ fontSize: 8, color: C.t4 }}>{mc.area}</span>
              </div>
              {wdi.map((di) => {
                const dc = cap[mc.id]?.[di] || { prod: 0, setup: 0, ops: 0, pcs: 0 };
                const tot = dc.prod + dc.setup;
                const u = tot / DAY_CAP;
                const isD = mSt[mc.id] === 'down';
                return (
                  <div
                    key={di}
                    style={{
                      background: isD ? C.rdS : hC(u),
                      borderRadius: 6,
                      padding: '5px 4px',
                      textAlign: 'center',
                      minHeight: 44,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: tot > 0 ? C.t1 : C.t4,
                        fontFamily: 'monospace',
                      }}
                    >
                      {tot > 0 ? Math.round(tot) : '—'}
                    </div>
                    {tot > 0 && (
                      <>
                        <div
                          style={{
                            fontSize: 9,
                            color: u > 1 ? C.rd : u > 0.85 ? C.yl : C.ac,
                            fontWeight: 600,
                          }}
                        >
                          {(u * 100).toFixed(0)}%
                        </div>
                        <div style={{ fontSize: 8, color: C.t4 }}>
                          {dc.ops}op · {(dc.pcs / 1000).toFixed(0)}K
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </React.Fragment>
          ))}
      </div>
    </Card>
  );
}
