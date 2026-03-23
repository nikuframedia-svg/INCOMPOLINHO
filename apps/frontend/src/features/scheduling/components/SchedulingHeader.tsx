import { AlertTriangle, Check, Moon, Server, Zap } from 'lucide-react';
import type { ScheduleValidationReport } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { useScheduleData } from '../../../hooks/useScheduleData';
import { useSettingsStore } from '../../../stores/useSettingsStore';
import { dot, Pill } from './atoms';

type Tab = { id: string; l: string };

const TABS: Tab[] = [
  { id: 'plan', l: 'Plano' },
  { id: 'simulate', l: 'Simular' },
];

export function SchedulingHeader({
  view,
  setView,
  downC,
  movesCount,
  autoMovesCount,
  blkOps,
  opsCount,
  machineCount,
  validation,
  otd,
  lateDeliveriesCount,
}: {
  view: string;
  setView: (v: string) => void;
  downC: number;
  movesCount: number;
  autoMovesCount: number;
  blkOps: number;
  opsCount: number;
  machineCount: number;
  validation: ScheduleValidationReport | null;
  otd?: number;
  lateDeliveriesCount?: number;
}) {
  const useServer = useSettingsStore((s) => s.useServerSolver);
  const setUseServer = useSettingsStore((s) => s.actions.setUseServerSolver);
  const thirdShiftDefault = useSettingsStore((s) => s.thirdShiftDefault);
  const { thirdShiftRecommended } = useScheduleData();

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: `1px solid ${C.bd}`,
        padding: '0 20px',
      }}
    >
      <div style={{ display: 'flex', gap: 2 }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setView(tab.id)}
            style={{
              padding: '8px 18px',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: 600,
              color: view === tab.id ? C.ac : C.t3,
              borderBottom: `2px solid ${view === tab.id ? C.ac : 'transparent'}`,
              fontFamily: 'inherit',
              letterSpacing: '.02em',
              transition: 'all .15s',
            }}
          >
            {tab.l}
            {tab.id === 'replan' && (movesCount > 0 || blkOps > 0) && (
              <TabDot color={blkOps > 0 ? C.rd : C.ac} />
            )}
            {tab.id === 'plan' && validation && !validation.valid && <TabDot color={C.rd} />}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {otd != null && (
          <Pill
            color={otd >= 0.95 ? C.gn : otd >= 0.8 ? C.yl : C.rd}
            active
            title={`On-Time Delivery: ${(otd * 100).toFixed(1)}%`}
          >
            OTD-D {(otd * 100).toFixed(0)}%
          </Pill>
        )}
        {(lateDeliveriesCount ?? 0) > 0 && (
          <Pill
            color={C.rd}
            active
            title={`${lateDeliveriesCount} entrega${lateDeliveriesCount! > 1 ? 's' : ''} em atraso`}
          >
            <AlertTriangle
              size={10}
              strokeWidth={2}
              style={{ display: 'inline', verticalAlign: 'middle' }}
            />{' '}
            {lateDeliveriesCount} atraso{lateDeliveriesCount! > 1 ? 's' : ''}
          </Pill>
        )}
        {thirdShiftRecommended && !thirdShiftDefault && (
          <Pill color={C.yl} active>
            <Moon
              size={10}
              strokeWidth={2}
              style={{ display: 'inline', verticalAlign: 'middle' }}
            />{' '}
            Noite recomendada
          </Pill>
        )}
        {downC > 0 && (
          <Pill
            color={C.rd}
            active
            title={`${downC} máquina${downC > 1 ? 's' : ''} parada${downC > 1 ? 's' : ''} — pode afectar entregas`}
          >
            <span style={dot(C.rd, true)} />
            {downC} DOWN
          </Pill>
        )}
        {movesCount > 0 && (
          <Pill
            color={C.ac}
            active
            title={`${movesCount} operação${movesCount > 1 ? 'ões' : ''} redistribuída${movesCount > 1 ? 's' : ''} para manter entregas`}
          >
            <Check
              size={10}
              strokeWidth={2}
              style={{ display: 'inline', verticalAlign: 'middle' }}
            />{' '}
            {movesCount}
          </Pill>
        )}
        {autoMovesCount > 0 && (
          <Pill
            color={C.bl}
            active
            title={`${autoMovesCount} movimentacao${autoMovesCount > 1 ? 'oes' : ''} automatica${autoMovesCount > 1 ? 's' : ''} pelo motor de optimizacao`}
          >
            <Zap
              size={10}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle' }}
            />{' '}
            {autoMovesCount} auto
          </Pill>
        )}
        {blkOps > 0 && (
          <Pill
            color={C.rd}
            active
            title={`${blkOps} operação${blkOps > 1 ? 'ões' : ''} bloqueada${blkOps > 1 ? 's' : ''} — sem máquina disponível`}
          >
            {blkOps} bloq
          </Pill>
        )}
        <Pill color={C.pp} active>
          {opsCount} ops
        </Pill>
        <Pill color={C.bl} active>
          {machineCount} máq
        </Pill>
        <button
          onClick={() => setUseServer(!useServer)}
          title={useServer ? 'CP-SAT server solver active' : 'Using client-side scheduling'}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '3px 8px',
            borderRadius: 4,
            border: `1px solid ${useServer ? C.ac : C.bd}`,
            background: useServer ? `${C.ac}18` : 'transparent',
            color: useServer ? C.ac : C.t3,
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 600,
            fontFamily: 'inherit',
            letterSpacing: '.02em',
          }}
        >
          <Server size={10} strokeWidth={2} />
          CP-SAT
        </button>
      </div>
    </div>
  );
}

function TabDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 5,
        height: 5,
        borderRadius: '50%',
        background: color,
        marginLeft: 6,
      }}
    />
  );
}
