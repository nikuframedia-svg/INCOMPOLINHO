import type { EngineData, EOp, ETool, OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { opsByDayFromWorkforce } from '@/utils/workforce';
import { Card, Metric } from '../atoms';
import { CapacityGrid, OperatorsChart } from './CapacityViews';
import { ComparisonTable } from './ComparisonTable';
import { MovesCard } from './MovesCard';

export function ScenarioDetails({
  scenario,
  sel,
  rankColor,
  ops,
  tools,
  data,
  getResourceDownDays,
  moveable,
  top3,
}: {
  scenario: OptResult;
  sel: number;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
  ops: EOp[];
  tools: ETool[];
  data: EngineData;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  moveable: Array<{ opId: string }>;
  top3: OptResult[];
}) {
  const rc = rankColor(sel);
  const s = scenario;
  const { machines, dates, dnames, nDays } = data;
  const opsPerDay = opsByDayFromWorkforce(s.workforceDemand, nDays);
  const avOps = Math.round(opsPerDay.reduce((a, d) => a + d.total, 0) / nDays || 10);
  const rankLabel = (i: number) =>
    i === 0 ? '#1 MELHOR' : i === 1 ? '#2' : i === 2 ? '#3' : `#${i + 1}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <KPIRow scenario={s} rc={rc} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 10 }}>
        <MovesCard scenario={s} rc={rc} ops={ops} tools={tools} moveable={moveable} />
        <CapacityGrid
          scenario={s}
          machines={machines}
          dates={dates}
          dnames={dnames}
          nDays={nDays}
          rc={rc}
          getResourceDownDays={getResourceDownDays}
        />
      </div>
      <OperatorsChart
        scenario={s}
        dnames={dnames}
        dates={dates}
        nDays={nDays}
        rc={rc}
        avOps={avOps}
      />
      <ComparisonTable top3={top3} sel={sel} rankColor={rankColor} rankLabel={rankLabel} />
    </div>
  );
}

function KPIRow({ scenario: s, rc }: { scenario: OptResult; rc: string }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
      {[
        {
          l: 'OTD-D',
          v: `${s.otdDelivery.toFixed(1)}%`,
          s: 'cumprimento datas',
          c: s.otdDelivery < 90 ? C.rd : s.otdDelivery < 95 ? C.yl : rc,
        },
        {
          l: 'OTD Produção',
          v: `${s.otd.toFixed(1)}%`,
          s: 'qty produzida',
          c: s.otd < 95 ? C.rd : rc,
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
  );
}
