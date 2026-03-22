/**
 * DecisionsPanel — Metrics summary, decision cards, and capacity impact.
 */
import { ArrowRight, Undo2 } from 'lucide-react';
import type { Block, DayLoad, EngineData, MoveAction, OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Card, Metric, Pill, toolColor } from '../atoms';
import { CapacityImpactPanel } from './CapacityImpactPanel';
import { DecisionCard } from './DecisionCard';
import type { ReplanProposal } from './types';

export interface DecisionsPanelProps {
  data: EngineData;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  mSt: Record<string, string>;
  moves: MoveAction[];
  undoMove: (opId: string) => void;
  applyMove: (opId: string, toM: string) => void;
  decs: ReplanProposal[];
  xai: string | null;
  setXai: (id: string | null) => void;
  neMetrics: (OptResult & { blocks: Block[] }) | null;
}

export function DecisionsPanel({
  data,
  blocks,
  cap,
  mSt,
  moves,
  undoMove,
  applyMove,
  decs,
  xai,
  setXai,
  neMetrics,
}: DecisionsPanelProps) {
  const { ops, dnames, toolMap: TM, tools } = data;
  const rp = decs.filter((d) => d.type === 'replan');
  const blk = decs.filter((d) => d.type === 'blocked');
  const lP = blk.reduce((a, d) => a + ((d.impact?.pcsLost as number) || 0), 0);
  const otd = neMetrics ? neMetrics.otdDelivery.toFixed(1) : '—';
  const sC = (s: string) => ({ critical: C.rd, high: C.yl, medium: C.bl, low: C.ac })[s] || C.t3;

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
        {[
          { l: 'OTD-D', v: `${otd}%`, c: parseFloat(otd) < 95 ? C.rd : C.ac },
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
        ].map((k) => (
          <Card key={k.l}>
            <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
          </Card>
        ))}
      </div>

      <div
        style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 12, alignItems: 'start' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {moves.length > 0 && (
            <Card style={{ padding: 12, background: C.acS, borderColor: `${C.ac}22` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.ac, marginBottom: 4 }}>
                Aplicadas ({moves.length})
              </div>
              {moves.map((mv, i) => {
                const op = ops.find((o) => o.id === mv.opId);
                return (
                  <div
                    key={`mv_${mv.opId}_${i}`}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}
                  >
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: toolColor(tools, op?.t || ''),
                        fontFamily: 'monospace',
                      }}
                    >
                      {op?.t}
                    </span>
                    <span
                      style={{
                        fontSize: 12,
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
                        fontSize: 12,
                        color: C.ac,
                        fontFamily: 'monospace',
                        fontWeight: 600,
                      }}
                    >
                      {mv.toM}
                    </span>
                    <span style={{ flex: 1, fontSize: 12, color: C.t3 }}>{op?.nm}</span>
                    <Pill
                      color={C.rd}
                      active
                      onClick={() => undoMove(mv.opId)}
                      size="sm"
                      aria-label={`Desfazer movimentação de ${op?.t ?? mv.opId}`}
                    >
                      <Undo2 size={9} strokeWidth={1.5} />
                    </Pill>
                  </div>
                );
              })}
            </Card>
          )}

          {decs.length === 0 && moves.length === 0 && (
            <Card style={{ padding: 40, textAlign: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.t3 }}>Sem ações pendentes</div>
              <div style={{ fontSize: 12, color: C.t4, marginTop: 4 }}>
                Marca máquinas/ferramentas DOWN para ativar
              </div>
            </Card>
          )}

          {decs.map((d, i) => (
            <DecisionCard
              key={`${d.id}_${i}`}
              d={d}
              dnames={dnames}
              xai={xai}
              setXai={setXai}
              applyMove={applyMove}
              sC={sC}
            />
          ))}
        </div>

        <CapacityImpactPanel data={data} blocks={blocks} cap={cap} mSt={mSt} moves={moves} />
      </div>
    </>
  );
}
