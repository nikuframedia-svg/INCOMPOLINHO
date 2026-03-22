/**
 * MachineCard — Single machine status card with Andon button.
 * Three states: normal (with PARADA button), down (timer + recovery), transition.
 * ISA-101: NEVER only color — always color + icon + text.
 */

import { AlertTriangle, CheckCircle } from 'lucide-react';
import { memo, useEffect, useState } from 'react';
import type { MachineState } from '@/components/Industrial/MachineStatusIndicator';
import { MachineStatusIndicator } from '@/components/Industrial/MachineStatusIndicator';
import { ProgressBar } from '@/components/Industrial/ProgressBar';
import type { Block } from '@/domain/types/scheduling';
import type { ActiveDowntime, AndonCategory } from '@/stores/useAndonStore';
import { fmtMin } from '@/utils/format';
import './MachineCard.css';

const CATEGORY_LABELS: Record<AndonCategory, string> = {
  avaria_mecanica: 'Avaria Mecanica/Electrica',
  setup_prolongado: 'Setup Prolongado',
  falta_material: 'Falta de Material',
  problema_qualidade: 'Problema de Qualidade',
  manutencao_preventiva: 'Manutencao Preventiva',
};

export interface MachineStatus {
  machineId: string;
  state: MachineState;
  currentBlock: Block | null;
  nextBlock: Block | null;
  utilization: number;
}

interface MachineCardProps {
  status: MachineStatus;
  downtime: ActiveDowntime | null;
  onAndonPress: (machineId: string) => void;
  onRecovery: (machineId: string) => void;
  /** Map opId → client name for context line */
  clientMap?: Record<string, string>;
  /** Count of blocks at risk if machine is down */
  blocksAtRisk?: number;
}

function formatElapsed(ms: number): string {
  const totalMin = Math.floor(ms / 60_000);
  if (totalMin < 60) return `${totalMin} min`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${h}h ${m}min`;
}

export const MachineCard = memo(function MachineCard({
  status,
  downtime,
  onAndonPress,
  onRecovery,
  clientMap,
  blocksAtRisk = 0,
}: MachineCardProps) {
  const { machineId, state, currentBlock, nextBlock, utilization } = status;

  // Live elapsed timer when machine is down
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!downtime) {
      setElapsed(0);
      return;
    }
    setElapsed(Date.now() - downtime.startedAt);
    const id = setInterval(() => {
      setElapsed(Date.now() - downtime.startedAt);
    }, 1000);
    return () => clearInterval(id);
  }, [downtime]);

  const isDown = downtime != null;
  const isMaintenance = isDown && downtime.category === 'manutencao_preventiva';
  const isIdle = !isDown && !currentBlock && utilization === 0;

  return (
    <div
      className={`msg__card${isDown ? (isMaintenance ? ' msg__card--maintenance' : ' msg__card--down') : isIdle ? ' msg__card--idle' : ''}`}
      data-testid={`msg-card-${machineId}`}
    >
      <div className="msg__header">
        <span className="msg__machine-id">{machineId}</span>
        <MachineStatusIndicator
          state={
            isDown
              ? downtime.category === 'manutencao_preventiva'
                ? 'maintenance'
                : 'outOfService'
              : isIdle
                ? 'idle'
                : state
          }
          compact
        />
      </div>

      {isDown ? (
        /* ── Down state ── */
        <div className="msg__down-body">
          <span className="msg__down-category">{CATEGORY_LABELS[downtime.category]}</span>
          <span
            className="msg__down-timer"
            style={isMaintenance ? { color: 'var(--semantic-blue)' } : undefined}
          >
            {isMaintenance ? 'EM MANUTENCAO' : 'PARADA'} ha {formatElapsed(elapsed)}
          </span>
          {downtime.estimatedMin != null && (
            <span className="msg__down-estimate">
              Estimativa:{' '}
              {downtime.estimatedMin >= 60
                ? `${downtime.estimatedMin / 60}h`
                : `${downtime.estimatedMin}min`}
            </span>
          )}
          {blocksAtRisk > 0 && (
            <span
              className="msg__down-consequence"
              style={{ fontSize: 12, color: 'var(--semantic-red)', marginTop: 4, display: 'block' }}
            >
              Afecta {blocksAtRisk} encomenda{blocksAtRisk > 1 ? 's' : ''} esta semana
            </span>
          )}
          <button
            type="button"
            className="msg__recovery-btn"
            onClick={() => onRecovery(machineId)}
            data-testid={`andon-recovery-${machineId}`}
          >
            <CheckCircle size={20} />
            RECUPERADA
          </button>
        </div>
      ) : isIdle ? (
        /* ── Idle state — no production, no Andon alarm ── */
        <div className="msg__idle-body">
          <span className="msg__idle-label">Sem produção hoje</span>
          <span className="msg__idle-sub">
            {nextBlock
              ? `Próxima operação: ${nextBlock.toolId}${clientMap?.[nextBlock.opId] ? ` (${clientMap[nextBlock.opId]})` : ''} — ${fmtMin(nextBlock.startMin)}`
              : 'Máquina disponível — sem ordens atribuídas'}
          </span>
        </div>
      ) : (
        /* ── Normal state ── */
        <>
          <div className="msg__current">
            {currentBlock ? (
              <>
                <span className="msg__sku">{currentBlock.sku}</span>
                <span className="msg__detail">
                  {currentBlock.toolId} · {currentBlock.qty.toLocaleString()} pcs
                  {clientMap?.[currentBlock.opId] ? ` · ${clientMap[currentBlock.opId]}` : ''}
                </span>
                <span className="msg__time">
                  {fmtMin(currentBlock.startMin)}–{fmtMin(currentBlock.endMin)}
                </span>
              </>
            ) : (
              <span className="msg__idle">Sem produção</span>
            )}
          </div>

          {nextBlock && (
            <div className="msg__next">
              <span className="msg__next-label">Proximo</span>
              <span className="msg__next-sku">
                {nextBlock.sku} · {fmtMin(nextBlock.startMin)}
              </span>
            </div>
          )}

          <div className="msg__util">
            <ProgressBar value={Math.round(utilization * 100)} size="sm" />
          </div>

          <button
            type="button"
            className="msg__andon-btn"
            onClick={() => onAndonPress(machineId)}
            data-testid={`andon-btn-${machineId}`}
          >
            <AlertTriangle size={20} />
            MAQUINA PARADA
          </button>
        </>
      )}
    </div>
  );
});
