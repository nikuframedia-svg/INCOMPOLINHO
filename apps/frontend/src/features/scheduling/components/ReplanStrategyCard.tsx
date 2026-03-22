/**
 * ReplanStrategyCard — Auto-evaluates severity and recommends replan strategy.
 *
 * Based on CLAUDE.md 4 replan layers:
 *   <30 min  → Right-shift
 *   30-120   → Match-up
 *   120-480  → Partial
 *   >480     → Full regen
 */

import { Zap } from 'lucide-react';
import type { Block, FailureEvent, ImpactReport } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Tag } from './atoms';
import './ReplanStrategyCard.css';

interface ReplanStrategyCardProps {
  failures: FailureEvent[];
  impacts: ImpactReport[];
  blocks: Block[];
  onSelectStrategy: (strategy: string) => void;
  selectedStrategy: string | null;
}

interface StrategyDef {
  id: string;
  label: string;
  range: string;
  color: string;
  description: string;
}

const STRATEGIES: StrategyDef[] = [
  {
    id: 'right_shift',
    label: 'Right-shift',
    range: '< 30 min',
    color: C.ac,
    description: 'Micro-ajuste — deslocar ops afectadas ligeiramente',
  },
  {
    id: 'match_up',
    label: 'Match-up',
    range: '30–120 min',
    color: C.bl,
    description: 'Rearranjar ops adjacentes para absorver gap',
  },
  {
    id: 'partial',
    label: 'Parcial',
    range: '2–8 horas',
    color: C.yl,
    description: 'Re-schedule parcial — mover ops para alt machines',
  },
  {
    id: 'full_regen',
    label: 'Regen Total',
    range: '> 8 horas',
    color: C.rd,
    description: 'Catástrofe — re-gerar plano completo',
  },
];

function recommendStrategy(impacts: ImpactReport[]): string {
  const totalMinutes = impacts.reduce((sum, imp) => sum + imp.summary.totalMinutesAtRisk, 0);
  if (totalMinutes < 30) return 'right_shift';
  if (totalMinutes < 120) return 'match_up';
  if (totalMinutes < 480) return 'partial';
  return 'full_regen';
}

export function ReplanStrategyCard({
  failures,
  impacts,
  blocks: _blocks,
  onSelectStrategy,
  selectedStrategy,
}: ReplanStrategyCardProps) {
  const totalMinutes = impacts.reduce((sum, imp) => sum + imp.summary.totalMinutesAtRisk, 0);
  const totalBlocks = impacts.reduce((sum, imp) => sum + imp.summary.totalBlocksAffected, 0);
  const totalQty = impacts.reduce((sum, imp) => sum + imp.summary.totalQtyAtRisk, 0);

  const recommended = recommendStrategy(impacts);
  const recDef = STRATEGIES.find((s) => s.id === recommended)!;

  if (failures.length === 0 || impacts.length === 0) return null;

  return (
    <div className="strategy-card">
      <div className="strategy-card__header">
        <Zap size={12} strokeWidth={1.5} style={{ color: recDef.color }} />
        <span className="strategy-card__title">Recomendação de Estratégia</span>
      </div>

      <div className="strategy-card__metrics">
        <div className="strategy-card__metric">
          <span className="strategy-card__metric-val">{Math.round(totalMinutes)} min</span>
          <span className="strategy-card__metric-label">Perturbação</span>
        </div>
        <div className="strategy-card__metric">
          <span className="strategy-card__metric-val">{totalBlocks}</span>
          <span className="strategy-card__metric-label">Blocos afectados</span>
        </div>
        <div className="strategy-card__metric">
          <span className="strategy-card__metric-val">{totalQty.toLocaleString()}</span>
          <span className="strategy-card__metric-label">Peças em risco</span>
        </div>
      </div>

      <div
        className="strategy-card__recommendation"
        style={{ borderColor: `${recDef.color}44`, background: `${recDef.color}08` }}
      >
        <Tag color={recDef.color}>{recDef.label.toUpperCase()}</Tag>
        <span className="strategy-card__rec-text">
          {recDef.label} recomendado — {recDef.description}
        </span>
      </div>

      <div className="strategy-card__buttons">
        {STRATEGIES.map((s) => {
          const isRec = s.id === recommended;
          const isSel = s.id === selectedStrategy;
          return (
            <button
              key={s.id}
              className={`strategy-card__btn${isSel ? ' strategy-card__btn--selected' : ''}`}
              style={{
                borderColor: isSel ? s.color : `${s.color}33`,
                background: isSel ? `${s.color}18` : 'transparent',
                color: isSel ? s.color : C.t3,
              }}
              onClick={() => onSelectStrategy(s.id)}
            >
              <span className="strategy-card__btn-label">
                {s.label}
                {isRec && <span className="strategy-card__btn-rec">REC</span>}
              </span>
              <span className="strategy-card__btn-range">{s.range}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
