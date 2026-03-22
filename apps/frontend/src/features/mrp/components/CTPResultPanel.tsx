import type { CTPResult } from '@/domain/mrp/mrp-types';
import { C } from '@/theme/color-bridge';
import { mono } from '../utils/mrp-helpers';
import { CTPChart } from './CTPChart';
import { KCard } from './KCard';

interface CTPResultPanelProps {
  result: CTPResult;
  dates: string[];
  dnames: string[];
  targetDay: number;
  label: string;
  machineName: string;
  /** If provided, shows "N dia(s) mais cedo" badge */
  daysEarlierThanPrimary?: number;
}

function confidenceLabel(c: CTPResult['confidence']): string {
  if (c === 'high') return 'ALTA';
  if (c === 'medium') return 'MÉDIA';
  return 'BAIXA';
}

function confidenceColor(c: CTPResult['confidence']): string {
  if (c === 'high') return C.ac;
  if (c === 'medium') return C.yl;
  return C.rd;
}

export function CTPResultPanel({
  result,
  dates,
  dnames,
  targetDay,
  label,
  machineName,
  daysEarlierThanPrimary,
}: CTPResultPanelProps) {
  return (
    <>
      <div
        style={{
          fontSize: 12,
          fontWeight: 500,
          color: C.t2,
          marginBottom: 4,
          marginTop: 8,
        }}
      >
        {label}: <span style={{ ...mono, color: C.t1 }}>{machineName}</span>
        {daysEarlierThanPrimary != null && daysEarlierThanPrimary > 0 && (
          <span style={{ fontSize: 12, color: C.ac, marginLeft: 8 }}>
            {daysEarlierThanPrimary} dia(s) mais cedo
          </span>
        )}
      </div>
      <div className="mrp__ctp-result">
        <KCard
          label="Viável"
          value={result.feasible ? 'SIM' : 'NÃO'}
          sub=""
          color={result.feasible ? C.ac : C.rd}
        />
        <KCard
          label="Dia Mais Cedo"
          value={result.earliestFeasibleDay !== null ? `D${result.earliestFeasibleDay}` : '-'}
          sub={
            result.earliestFeasibleDay !== null
              ? (dates[result.earliestFeasibleDay] ?? `D${result.earliestFeasibleDay}`)
              : 'sem capacidade'
          }
          color={result.earliestFeasibleDay !== null ? C.t1 : C.rd}
        />
        <KCard
          label="Confiança"
          value={confidenceLabel(result.confidence)}
          sub=""
          color={confidenceColor(result.confidence)}
        />
        <KCard
          label="Capacidade"
          value={`${result.requiredMin}m`}
          sub={`disponível: ${result.availableMinOnDay}m`}
          color={C.t1}
        />
      </div>
      <div className="mrp__card" style={{ marginBottom: 12 }}>
        {result.reason && (
          <div style={{ fontSize: 12, color: C.t2, marginBottom: 12 }}>{result.reason}</div>
        )}
        <CTPChart
          timeline={result.capacityTimeline}
          dates={dates}
          dnames={dnames}
          targetDay={targetDay}
        />
      </div>
    </>
  );
}
