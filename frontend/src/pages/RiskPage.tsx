import { Fragment, useMemo, useState } from "react";
import { T } from "../theme/tokens";
import { getRisk, getLateDeliveries, getWorkforce } from "../api/endpoints";
import type { HeatmapCell } from "../api/types";
import { usePlanQuery } from "../hooks/usePlanQuery";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Num } from "../components/ui/Num";
import { Pill } from "../components/ui/Pill";

type Tab = "overview" | "late" | "workforce";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Visão geral" },
  { id: "late", label: "Atrasos" },
  { id: "workforce", label: "Equipa" },
];

const thStyle: React.CSSProperties = {
  fontSize: 11, color: T.tertiary, fontWeight: 500, textAlign: "left",
  padding: "8px 12px", borderBottom: `1px solid ${T.border}`,
  position: "sticky", top: 0, background: T.card,
  textTransform: "uppercase", letterSpacing: "0.04em",
};

const tdStyle: React.CSSProperties = {
  fontSize: 12, color: T.primary, padding: "6px 12px",
  borderBottom: `1px solid ${T.border}`, fontFamily: T.mono,
};

const riskColor = (level: string) => {
  if (level === "critical") return T.red;
  if (level === "high") return T.orange;
  if (level === "medium") return T.yellow;
  return T.green;
};

const RISK_LEVEL_LABELS: Record<string, string> = {
  critical: "Crítico",
  high: "Alto",
  medium: "Médio",
  low: "Baixo",
  none: "Sem risco",
};

const riskLevelLabel = (level: string | null | undefined) =>
  level ? RISK_LEVEL_LABELS[level] ?? "Sem classificação" : "sem dados";

const RISK_STATUS_LABELS: Record<string, string> = {
  late: "Atrasado",
  at_limit: "No limite",
  short_slack: "Folga curta",
};

/** Pill colour follows the status label, so "No limite" never looks like "Atrasado". */
const RISK_STATUS_COLORS: Record<string, string> = {
  late: T.red,
  at_limit: T.orange,
  short_slack: T.yellow,
};

const plural = (count: number, singular: string, pluralForm: string) =>
  `${count} ${Math.abs(count) === 1 ? singular : pluralForm}`;

/** Negative slack is lateness: say "N dias de atraso", never "Folga: -N". */
const slackText = (slack: number | null | undefined) => {
  const value = Number(slack ?? 0);
  if (!Number.isFinite(value)) return "Folga: —";
  if (value < 0) return `${plural(Math.abs(value), "dia", "dias")} de atraso`;
  return `Folga: ${plural(value, "dia", "dias")}`;
};

const causeLabel = (cause: string) => {
  const map: Record<string, string> = {
    capacity: "Capacidade",
    setup_overhead: "Setup",
    priority_conflict: "Prioridade",
    lead_time: "Antecedência",
    tool_contention: "Conflito de ferramenta",
  };
  return map[cause] ?? cause;
};

const loadRisk = () => Promise.all([getRisk(), getLateDeliveries(), getWorkforce()]);

export function RiskPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const { data: response, error } = usePlanQuery("risk", loadRisk);
  const [risk, late, workforce] = response ?? [null, null, null];
  const [causeFilter, setCauseFilter] = useState<string | null>(null);

  // Heatmap data
  const heatmapData = useMemo(() => {
    if (!risk) return { machines: [] as string[], days: [] as number[], cells: new Map<string, HeatmapCell>() };
    const heatmap = risk.heatmap ?? [];
    const machines = [...new Set(heatmap.map((c) => c.machine_id))].sort();
    const days = [...new Set(heatmap.map((c) => c.day_idx))].sort((a, b) => a - b);
    const cells = new Map<string, HeatmapCell>();
    for (const c of heatmap) cells.set(`${c.machine_id}-${c.day_idx}`, c);
    return { machines, days, cells };
  }, [risk]);

  const filteredAnalyses = useMemo(() => {
    if (!late) return [];
    if (!causeFilter) return late.analyses;
    return late.analyses.filter((a) => a.root_cause === causeFilter);
  }, [late, causeFilter]);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!risk) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const healthColor = risk.health_score >= 80 ? T.green : risk.health_score >= 50 ? T.orange : T.red;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Tab bar */}
      <div style={{ display: "flex", gap: 4 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              background: tab === t.id ? T.elevated : "transparent",
              border: `1px solid ${tab === t.id ? T.borderHover : T.border}`,
              color: tab === t.id ? T.primary : T.secondary,
              borderRadius: 8, padding: "5px 12px", cursor: "pointer",
              fontSize: 12, fontWeight: tab === t.id ? 600 : 400, fontFamily: "inherit",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview ── */}
      {tab === "overview" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            <Card style={{ textAlign: "center" }}>
              <Label>Saúde do plano</Label>
              <Num size={48} color={healthColor}>{risk.health_score}</Num>
              <div style={{ marginTop: 4, color: T.tertiary, fontSize: 10 }}>
                80–100 estável · 50–79 atenção · &lt;50 crítico
              </div>
            </Card>
            <Card style={{ textAlign: "center" }}>
              <Label>Riscos críticos</Label>
              <Num size={36} color={risk.critical_count > 0 ? T.red : T.green}>{risk.critical_count}</Num>
            </Card>
            <Card style={{ textAlign: "center" }}>
              <Label>Recurso limitante</Label>
              <div style={{ marginTop: 8 }}>
                {risk.bottleneck ? <Pill color={T.red}>{risk.bottleneck}</Pill> : <span style={{ color: T.secondary, fontSize: 13 }}>Nenhum</span>}
              </div>
            </Card>
          </div>

          {/* Heatmap */}
          {heatmapData.machines.length > 0 && (
            <Card style={{ padding: 0, overflow: "auto" }}>
              <div style={{ padding: "12px 16px 4px" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>Mapa de risco</span>
              </div>
              <div style={{ padding: "8px 16px 16px", overflowX: "auto" }}>
                <div style={{ display: "grid", gridTemplateColumns: `80px repeat(${heatmapData.days.length}, 28px)`, gap: 2 }}>
                  {/* Header row */}
                  <div />
                  {heatmapData.days.map((d) => (
                    <div key={d} style={{ fontSize: 8, color: T.tertiary, textAlign: "center", fontFamily: T.mono }}>
                      {d % 5 === 0 ? d : ""}
                    </div>
                  ))}
                  {/* Machine rows */}
                  {heatmapData.machines.map((m) => (
                    <Fragment key={m}>
                      <div style={{ fontSize: 10, color: T.secondary, fontFamily: T.mono, display: "flex", alignItems: "center" }}>{m}</div>
                      {heatmapData.days.map((d) => {
                        const cell = heatmapData.cells.get(`${m}-${d}`);
                        const level = cell?.risk_level;
                        const bg = level ? `${riskColor(level)}${level === "critical" ? "88" : level === "high" ? "55" : level === "medium" ? "33" : "18"}` : `${T.border}`;
                        const utilPct = cell?.utilization === null ? null : Math.round((cell?.utilization ?? 0) * 100);
                        return (
                          <div
                            key={d}
                            title={[
                              `Máquina ${m}`,
                              `Dia ${d}`,
                              `Risco: ${riskLevelLabel(level)}`,
                              utilPct === null ? "Inconsistência: carga sem capacidade disponível" : `Utilização: ${utilPct}%`,
                              `Carga: ${Math.round(cell?.load_min ?? 0)} min`,
                              `Capacidade: ${Math.round(cell?.capacity_min ?? 0)} min`,
                              cell?.min_slack_min != null && cell.min_slack_min >= 0 ? `Margem mínima: ${Math.round(cell.min_slack_min)} min` : "",
                            ].filter(Boolean).join(" · ")}
                            style={{
                              width: 26,
                              height: 22,
                              borderRadius: 3,
                              background: bg,
                              color: T.primary,
                              fontSize: 8,
                              fontFamily: T.mono,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              border: `1px solid ${T.card}`,
                            }}
                          >
                            {utilPct === null ? "!" : utilPct > 0 ? utilPct : ""}
                          </div>
                        );
                      })}
                    </Fragment>
                  ))}
                </div>
              </div>
            </Card>
          )}

          {/* Top risks */}
          {risk.top_risks.length > 0 && (
            <Card style={{ padding: 0 }}>
              <div style={{ padding: "12px 16px 8px" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>Riscos principais</span>
              </div>
              {risk.top_risks.map((r, i) => (
                <div key={i} style={{ padding: "8px 16px", borderTop: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 12 }}>
                  {typeof r.status === "string" && RISK_STATUS_LABELS[r.status] ? (
                    <Pill color={RISK_STATUS_COLORS[r.status]}>{RISK_STATUS_LABELS[r.status]}</Pill>
                  ) : (
                    <Pill color={riskColor(r.risk_level)}>{riskLevelLabel(r.risk_level)}</Pill>
                  )}
                  <span style={{ fontSize: 12, fontFamily: T.mono, color: T.primary, flex: 1 }}>{r.sku}</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>{r.machine_id}</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>{slackText(r.slack_days)}</span>
                </div>
              ))}
            </Card>
          )}
        </>
      )}

      {/* ── Late Deliveries ── */}
      {tab === "late" && late && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            <Card>
              <Label>Total de atrasos</Label>
              <Num size={36} color={late.tardy_count > 0 ? T.red : T.green}>{late.tardy_count}</Num>
            </Card>
            <Card>
              <Label>Atraso médio (dias)</Label>
              <Num size={36}>{late.avg_delay?.toFixed(1) ?? "0"}</Num>
            </Card>
            <Card>
              <Label>Máquina com mais atraso</Label>
              <div style={{ marginTop: 8 }}>
                {late.worst_machine ? <Pill color={T.red}>{late.worst_machine}</Pill> : <span style={{ color: T.secondary, fontSize: 13 }}>-</span>}
              </div>
            </Card>
          </div>

          <Card>
            <Label style={{ marginBottom: 8 }}>Recomendação</Label>
            <div style={{ fontSize: 13, color: T.primary, lineHeight: 1.6 }}>{late.suggestion}</div>
          </Card>

          {/* Cause filter chips */}
          {Object.keys(late.by_cause).length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button
                onClick={() => setCauseFilter(null)}
                style={{
                  background: causeFilter === null ? T.elevated : "transparent",
                  border: `1px solid ${T.border}`,
                  borderRadius: 6, padding: "3px 10px", cursor: "pointer",
                  fontSize: 11, color: causeFilter === null ? T.primary : T.secondary, fontFamily: "inherit",
                }}
              >
                Todos ({late.analyses.length})
              </button>
              {Object.entries(late.by_cause).map(([cause, count]) => (
                <button
                  key={cause}
                  onClick={() => setCauseFilter(causeFilter === cause ? null : cause)}
                  style={{
                    background: causeFilter === cause ? T.elevated : "transparent",
                    border: `1px solid ${T.border}`,
                    borderRadius: 6, padding: "3px 10px", cursor: "pointer",
                    fontSize: 11, color: causeFilter === cause ? T.primary : T.secondary, fontFamily: "inherit",
                  }}
                >
                  {causeLabel(cause)} ({count})
                </button>
              ))}
            </div>
          )}

          <Card style={{ padding: 0, overflow: "auto", maxHeight: 500 }}>
            <table style={{ width: "100%", minWidth: 900, borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>Referência</th>
                  <th style={thStyle}>Máquina</th>
                  <th style={thStyle}>Entrega cliente</th>
                  <th style={thStyle}>Saída fábrica</th>
                  <th style={thStyle}>Pronto cliente</th>
                  <th style={thStyle}>Atraso (d)</th>
                  <th style={thStyle}>Causa</th>
                  <th style={thStyle}>Explicação</th>
                </tr>
              </thead>
              <tbody>
                {filteredAnalyses.map((a, i) => (
                  <tr key={i}>
                    <td style={tdStyle}>{a.sku}</td>
                    <td style={tdStyle}>{a.machine_id}</td>
                    <td style={tdStyle}>{a.edd}</td>
                    <td style={tdStyle}>{a.completion_day}</td>
                    <td style={tdStyle}>{a.customer_ready_day ?? a.completion_day}</td>
                    <td style={{ ...tdStyle, color: T.red }}>{a.delay_days}</td>
                    <td style={tdStyle}><Pill color={T.orange}>{causeLabel(a.root_cause)}</Pill></td>
                    <td style={{ ...tdStyle, fontFamily: T.sans, fontSize: 11, color: T.secondary, maxWidth: 250 }}>{a.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {/* ── Workforce ── */}
      {tab === "workforce" && workforce && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
            <Card>
              <Label>Dia de pico</Label>
              <Num size={28}>D{workforce.peak_day}</Num>
            </Card>
            <Card>
              <Label>Pico de operadores</Label>
              <Num size={28}>{workforce.peak_required}</Num>
            </Card>
            <Card>
              <Label>Média</Label>
              <Num size={28}>{workforce.avg_required.toFixed(1)}</Num>
            </Card>
            <Card>
              <Label>Dias com défice</Label>
              <Num size={28} color={workforce.deficit_days > 0 ? T.red : T.green}>{workforce.deficit_days}</Num>
            </Card>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Label>Tendência:</Label>
            <Pill color={workforce.trend === "increasing" ? T.orange : workforce.trend === "decreasing" ? T.green : T.blue}>
              {workforce.trend === "increasing" ? "Crescente" : workforce.trend === "decreasing" ? "Decrescente" : "Estável"}
            </Pill>
          </div>

          <Card style={{ padding: 0, overflow: "auto", maxHeight: 500 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>Dia</th>
                  <th style={thStyle}>Turno</th>
                  <th style={thStyle}>Grupo</th>
                  <th style={thStyle}>Necessários</th>
                  <th style={thStyle}>Disponíveis</th>
                  <th style={thStyle}>Saldo</th>
                </tr>
              </thead>
              <tbody>
                {workforce.daily.map((d, i) => (
                  <tr key={i}>
                    <td style={tdStyle}>D{d.day_idx}</td>
                    <td style={tdStyle}>{d.shift}</td>
                    <td style={{ ...tdStyle, fontFamily: T.sans }}>{d.machine_group}</td>
                    <td style={tdStyle}>{d.required}</td>
                    <td style={tdStyle}>{d.available}</td>
                    <td style={{ ...tdStyle, color: d.surplus_or_deficit < 0 ? T.red : T.green, fontWeight: 600 }}>
                      {d.surplus_or_deficit > 0 ? "+" : ""}{d.surplus_or_deficit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

    </div>
  );
}
