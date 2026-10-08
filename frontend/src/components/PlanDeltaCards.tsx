import type { DeltaReport } from "../api/types";
import { T } from "../theme/tokens";
import { Card } from "./ui/Card";
import { Label } from "./ui/Label";
import { Num } from "./ui/Num";

function DeltaCard({ label, before, after, suffix = "", higher = false }: {
  label: string;
  before: number;
  after: number;
  suffix?: string;
  higher?: boolean;
}) {
  const improved = higher ? after > before : after < before;
  const worsened = higher ? after < before : after > before;
  const color = improved ? T.green : worsened ? T.red : T.secondary;
  const format = (value: number) => value % 1 !== 0 ? value.toFixed(1) : value;

  return (
    <Card style={{ textAlign: "center" }}>
      <Label>{label}</Label>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 4, marginTop: 4 }}>
        <span style={{ fontSize: 12, color: T.tertiary, fontFamily: T.mono }}>
          {format(before)}{suffix}
        </span>
        <span style={{ fontSize: 12, color }}> → </span>
        <Num size={20} color={color}>{format(after)}{suffix}</Num>
      </div>
    </Card>
  );
}

export function PlanDeltaCards({ delta }: { delta: DeltaReport }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12 }}>
      <DeltaCard label="Lotes no prazo" before={delta.otd_before} after={delta.otd_after} suffix="%" higher />
      <DeltaCard label="Cumprimento diário" before={delta.otd_d_before} after={delta.otd_d_after} suffix="%" higher />
      <DeltaCard label="Setups" before={delta.setups_before} after={delta.setups_after} />
      <DeltaCard label="Lotes atrasados" before={delta.tardy_before} after={delta.tardy_after} />
      <DeltaCard label="Envios sub. em atraso" before={delta.subcontract_dispatch_before ?? 0} after={delta.subcontract_dispatch_after ?? 0} />
      <DeltaCard label="Atraso sub." before={delta.subcontract_dispatch_late_workdays_before ?? 0} after={delta.subcontract_dispatch_late_workdays_after ?? 0} suffix="du" />
      <DeltaCard label="Antecipação" before={delta.earliness_before} after={delta.earliness_after} suffix="d" />
      <DeltaCard label="Material fora janela" before={delta.early_window_before ?? 0} after={delta.early_window_after ?? 0} />
      <DeltaCard label="Ocupação média" before={delta.utilization_before ?? 0} after={delta.utilization_after ?? 0} suffix="%" />
    </div>
  );
}
