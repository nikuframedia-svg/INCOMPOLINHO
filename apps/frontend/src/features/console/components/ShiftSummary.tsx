/**
 * ShiftSummary — Automatic shift handover report.
 *
 * Shows production vs planned (per machine), open alerts, late orders,
 * shift decisions with total deviation cost, next shift priorities,
 * TrustIndex badge, and free-form notes.
 */

import type { LucideIcon } from 'lucide-react';
import { ArrowLeftRight, FastForward, Layers, Moon, Scissors, Zap } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Collapsible } from '@/components/Common/Collapsible';
import type { MachineState } from '@/components/Industrial/MachineStatusIndicator';
import { MachineStatusIndicator } from '@/components/Industrial/MachineStatusIndicator';
import { useActiveAlerts } from '@/features/alerts';
import type { DayData, MachineLoad } from '@/hooks/useDayData';
import type { Block } from '@/lib/engine';
import { fmtMin } from '@/lib/engine';
import { useDataStore } from '@/stores/useDataStore';
import './ShiftSummary.css';

// Shift label: X=A(07-15:30), Y=B(15:30-00), Z=Noite
type ShiftLabel = 'A' | 'B';

interface ShiftSummaryProps {
  dayData: DayData;
  allBlocks: Block[];
  shift: ShiftLabel;
  onNavigateToBlock?: (opId: string) => void;
}

// ── Decision categories (same as ActiveDecisions) ──

interface DecCat {
  label: string;
  Icon: LucideIcon;
  colorVar: string;
}

const DEC_CATS: Record<string, DecCat> = {
  AUTO_REPLAN_MOVE: { label: 'Realocacao', Icon: ArrowLeftRight, colorVar: 'var(--accent)' },
  ALTERNATIVE_MACHINE: { label: 'Realocacao', Icon: ArrowLeftRight, colorVar: 'var(--accent)' },
  AUTO_REPLAN_ADVANCE: { label: 'Antecipacao', Icon: FastForward, colorVar: 'var(--accent)' },
  ADVANCE_PRODUCTION: { label: 'Antecipacao', Icon: FastForward, colorVar: 'var(--accent)' },
  AUTO_REPLAN_OVERTIME: { label: 'Turno Extra', Icon: Moon, colorVar: 'var(--semantic-amber)' },
  AUTO_REPLAN_THIRD_SHIFT: { label: 'Turno Noite', Icon: Moon, colorVar: 'var(--semantic-amber)' },
  LOAD_LEVEL: { label: 'Resequencia', Icon: Layers, colorVar: 'var(--accent)' },
  AUTO_REPLAN_SPLIT: { label: 'Divisão', Icon: Scissors, colorVar: 'var(--accent)' },
};

const DEF_CAT: DecCat = { label: 'Sistema', Icon: Zap, colorVar: 'var(--text-muted)' };

function getCat(type: string): DecCat {
  return DEC_CATS[type] ?? DEF_CAT;
}

function shiftCode(s: ShiftLabel): 'X' | 'Y' {
  return s === 'A' ? 'X' : 'Y';
}
function shiftRange(s: ShiftLabel): string {
  return s === 'A' ? '07:00–15:30' : '15:30–00:00';
}
function nextShiftLabel(s: ShiftLabel): ShiftLabel {
  return s === 'A' ? 'B' : 'A';
}

function getNowMin(): number {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

function deriveMachineState(ml: MachineLoad, nowMin: number, isToday: boolean): MachineState {
  if (!isToday) return ml.blocks.length > 0 ? 'running' : 'stopped';
  const current = ml.blocks.find((b) => b.startMin <= nowMin && b.endMin > nowMin);
  if (current) return 'running';
  const hasSetup = ml.blocks.some(
    (b) => b.setupS != null && b.setupS <= nowMin && (b.setupE ?? b.startMin) > nowMin,
  );
  if (hasSetup) return 'transition';
  return 'stopped';
}

function trustLabel(score: number): { text: string; color: string } {
  if (score >= 0.9) return { text: 'Full Auto', color: 'var(--semantic-green)' };
  if (score >= 0.7) return { text: 'Monitoring', color: 'var(--accent)' };
  if (score >= 0.5) return { text: 'Suggestion', color: 'var(--semantic-amber)' };
  return { text: 'Manual', color: 'var(--semantic-red)' };
}

export function ShiftSummary({ dayData, allBlocks, shift, onNavigateToBlock }: ShiftSummaryProps) {
  const [notes, setNotes] = useState('');
  const activeAlerts = useActiveAlerts();
  const trustScore = useDataStore((s) => s.meta?.trustScore);

  const sc = shiftCode(shift);
  const nowMin = useMemo(() => getNowMin(), []);
  const isToday = dayData.date === new Date().toISOString().slice(0, 10);

  // ── Shift blocks ──
  const shiftBlocks = useMemo(
    () => dayData.blocks.filter((b) => b.shift === sc),
    [dayData.blocks, sc],
  );

  // ── Production vs planned per machine ──
  const machineRows = useMemo(() => {
    return dayData.machineLoads.map((ml) => {
      const mBlocks = shiftBlocks.filter((b) => b.machineId === ml.machineId);
      const planned = mBlocks.reduce((s, b) => s + b.qty, 0);
      // Approximation: completed blocks have endMin <= nowMin (only meaningful today)
      const completed = isToday
        ? mBlocks.filter((b) => b.endMin <= nowMin)
        : mBlocks.filter((b) => b.type === 'ok');
      const produced = completed.reduce((s, b) => s + b.qty, 0);
      const delta = produced - planned;
      const state = deriveMachineState(ml, nowMin, isToday);
      return { machineId: ml.machineId, planned, produced, delta, state };
    });
  }, [dayData.machineLoads, shiftBlocks, nowMin, isToday]);

  // ── Late blocks in this shift ──
  const lateBlocks = useMemo(() => shiftBlocks.filter((b) => b.type === 'overflow'), [shiftBlocks]);

  // ── Decisions in this shift (human overrides) ──
  const shiftDecisions = useMemo(() => {
    return dayData.decisions.filter((d) => {
      const meta = d.metadata as Record<string, unknown> | undefined;
      return meta?.source === 'user';
    });
  }, [dayData.decisions]);

  const totalDeviationCost = useMemo(() => {
    let total = 0;
    for (const d of shiftDecisions) {
      const cost = (d.metadata as Record<string, unknown>)?.deviationCost;
      if (typeof cost === 'number') total += cost;
    }
    return total;
  }, [shiftDecisions]);

  // ── Next shift priorities (top 5 by eddDay) ──
  const nextShift = shiftCode(nextShiftLabel(shift));
  const nextPriorities = useMemo(() => {
    return allBlocks
      .filter((b) => b.dayIdx === dayData.dayIdx && b.shift === nextShift)
      .sort((a, b) => (a.eddDay ?? 999) - (b.eddDay ?? 999))
      .slice(0, 5);
  }, [allBlocks, dayData.dayIdx, nextShift]);

  const trust = trustScore != null ? trustLabel(trustScore) : null;

  return (
    <div data-testid="shift-summary">
      <Collapsible title="Passagem de Turno" defaultOpen badge={`${shift}`}>
        {/* Header */}
        <div className="shsm__header">
          <span className="shsm__title">
            Turno {shift}→{nextShiftLabel(shift)} — {dayData.date}
          </span>
          <span className="shsm__shift-badge">
            {shift}: {shiftRange(shift)}
          </span>
        </div>

        {/* 1. Production vs Planned */}
        <div className="shsm__section">
          <div className="shsm__section-title">Produção vs Planeado</div>
          <table className="shsm__table">
            <thead>
              <tr>
                <th>Máquina</th>
                <th>Planeado</th>
                <th>Produzido</th>
                <th>Delta</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {machineRows.map((r) => (
                <tr key={r.machineId}>
                  <td>{r.machineId}</td>
                  <td>{r.planned.toLocaleString()}</td>
                  <td>{r.produced.toLocaleString()}</td>
                  <td>
                    <span
                      className={
                        r.delta > 0
                          ? 'shsm__delta--positive'
                          : r.delta < 0
                            ? 'shsm__delta--negative'
                            : 'shsm__delta--zero'
                      }
                    >
                      {r.delta > 0 ? '+' : ''}
                      {r.delta.toLocaleString()}
                    </span>
                  </td>
                  <td>
                    <MachineStatusIndicator state={r.state} compact />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 2. Alerts & Late Orders */}
        <div className="shsm__section">
          <div className="shsm__section-title">
            Alertas / Ordens Atrasadas ({activeAlerts.length + lateBlocks.length})
          </div>
          {activeAlerts.length === 0 && lateBlocks.length === 0 ? (
            <div className="shsm__empty">Sem alertas ou atrasos neste turno.</div>
          ) : (
            <div className="shsm__alert-list">
              {lateBlocks.map((b) => (
                <div
                  key={b.opId}
                  className="shsm__alert-item"
                  style={{ cursor: onNavigateToBlock ? 'pointer' : undefined }}
                  onClick={onNavigateToBlock ? () => onNavigateToBlock(b.opId) : undefined}
                >
                  <span
                    className="shsm__alert-badge"
                    style={{ background: 'rgba(239,68,68,0.12)', color: 'var(--semantic-red)' }}
                  >
                    ATRASO
                  </span>
                  {b.sku} — {b.machineId} — {b.overflowMin ?? 0}min overflow
                </div>
              ))}
              {activeAlerts.slice(0, 5).map((a) => (
                <div key={a.id} className="shsm__alert-item">
                  <span
                    className="shsm__alert-badge"
                    style={{
                      background:
                        a.priority === 'CRITICAL'
                          ? 'rgba(239,68,68,0.12)'
                          : 'rgba(245,158,11,0.12)',
                      color:
                        a.priority === 'CRITICAL' ? 'var(--semantic-red)' : 'var(--semantic-amber)',
                    }}
                  >
                    {a.priority}
                  </span>
                  {a.cause}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 3. Shift Decisions (Firewall) */}
        <div className="shsm__section">
          <div className="shsm__section-title">
            Decisões do Turno
            {totalDeviationCost > 0 && (
              <span className="shsm__cost-total" style={{ marginLeft: 8 }}>
                Custo total: +{totalDeviationCost} min
              </span>
            )}
          </div>
          {shiftDecisions.length === 0 ? (
            <div className="shsm__empty">Todas as decisões foram automáticas.</div>
          ) : (
            <div className="shsm__alert-list">
              {shiftDecisions.map((d) => {
                const cat = getCat(d.type);
                const Icon = cat.Icon;
                const cost = (d.metadata as Record<string, unknown>)?.deviationCost as
                  | number
                  | undefined;
                return (
                  <div key={d.id} className="shsm__decision-item">
                    <Icon size={12} style={{ color: cat.colorVar, flexShrink: 0 }} />
                    <span style={{ color: cat.colorVar, fontWeight: 600 }}>{cat.label}</span>
                    <span>{d.detail}</span>
                    {cost != null && <span className="shsm__cost-total">+{cost} min</span>}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 4. Next Shift Priorities */}
        <div className="shsm__section">
          <div className="shsm__section-title">Top 5 Prioridades Turno {nextShiftLabel(shift)}</div>
          {nextPriorities.length === 0 ? (
            <div className="shsm__empty">Sem operações no próximo turno.</div>
          ) : (
            <div className="shsm__priority-list">
              {nextPriorities.map((b) => (
                <div
                  key={b.opId}
                  className="shsm__priority-item"
                  style={{ cursor: onNavigateToBlock ? 'pointer' : undefined }}
                  onClick={onNavigateToBlock ? () => onNavigateToBlock(b.opId) : undefined}
                >
                  <span className="shsm__priority-sku">{b.sku}</span>
                  <span className="shsm__priority-meta">
                    {b.machineId} · {fmtMin(b.startMin)}–{fmtMin(b.endMin)}
                    {b.eddDay != null ? ` · EDD d${b.eddDay}` : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 5. TrustIndex */}
        <div className="shsm__section">
          <div className="shsm__section-title">TrustIndex dos Dados</div>
          {trust ? (
            <div className="shsm__trust">
              <span className="shsm__trust-score" style={{ color: trust.color }}>
                {(trustScore! * 100).toFixed(0)}%
              </span>
              <span
                className="shsm__trust-badge"
                style={{ background: `${trust.color}15`, color: trust.color }}
              >
                {trust.text}
              </span>
            </div>
          ) : (
            <div className="shsm__empty">Sem dados de TrustIndex.</div>
          )}
        </div>

        {/* 6. Free Notes */}
        <div className="shsm__section">
          <div className="shsm__section-title">Notas</div>
          <textarea
            className="shsm__notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Observações para o próximo turno..."
          />
        </div>
      </Collapsible>
    </div>
  );
}
