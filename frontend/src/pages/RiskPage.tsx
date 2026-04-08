import { Fragment, useEffect, useMemo, useState } from "react";
import { T } from "../theme/tokens";
import { getRisk, getLateDeliveries, getWorkforce } from "../api/endpoints";
import type { RiskResult, LateDeliveryReport, WorkforceForecast } from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Num } from "../components/ui/Num";
import { Pill } from "../components/ui/Pill";

type Tab = "overview" | "late" | "workforce" | "proposals";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Visao Geral" },
  { id: "late", label: "Atrasos" },
  { id: "workforce", label: "Mao de Obra" },
  { id: "proposals", label: "Propostas" },
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

const causeLabel = (cause: string) => {
  const map: Record<string, string> = {
    capacity: "Capacidade",
    setup_overhead: "Setup",
    priority_conflict: "Prioridade",
    lead_time: "Lead Time",
    tool_contention: "Contencao Ferramenta",
  };
  return map[cause] ?? cause;
};

export function RiskPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [risk, setRisk] = useState<RiskResult | null>(null);
  const [late, setLate] = useState<LateDeliveryReport | null>(null);
  const [workforce, setWorkforce] = useState<WorkforceForecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [causeFilter, setCauseFilter] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getRisk(), getLateDeliveries(), getWorkforce()])
      .then(([r, l, w]) => { setRisk(r); setLate(l); setWorkforce(w); })
      .catch((e) => setError(String(e)));
  }, []);

  // Heatmap data
  const heatmapData = useMemo(() => {
    if (!risk) return { machines: [] as string[], days: [] as number[], cells: new Map<string, string>() };
    const heatmap = risk.heatmap ?? [];
    const machines = [...new Set(heatmap.map((c) => c.machine_id))].sort();
    const days = [...new Set(heatmap.map((c) => c.day_idx))].sort((a, b) => a - b);
    const cells = new Map<string, string>();
    for (const c of heatmap) cells.set(`${c.machine_id}-${c.day_idx}`, c.risk_level);
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
              <Label>Health Score</Label>
              <Num size={48} color={healthColor}>{risk.health_score}</Num>
            </Card>
            <Card style={{ textAlign: "center" }}>
              <Label>Riscos Criticos</Label>
              <Num size={36} color={risk.critical_count > 0 ? T.red : T.green}>{risk.critical_count}</Num>
            </Card>
            <Card style={{ textAlign: "center" }}>
              <Label>Bottleneck</Label>
              <div style={{ marginTop: 8 }}>
                {risk.bottleneck ? <Pill color={T.red}>{risk.bottleneck}</Pill> : <span style={{ color: T.secondary, fontSize: 13 }}>Nenhum</span>}
              </div>
            </Card>
          </div>

          {/* Heatmap */}
          {heatmapData.machines.length > 0 && (
            <Card style={{ padding: 0, overflow: "auto" }}>
              <div style={{ padding: "12px 16px 4px" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>Heatmap de Risco</span>
              </div>
              <div style={{ padding: "8px 16px 16px", overflowX: "auto" }}>
                <div style={{ display: "grid", gridTemplateColumns: `80px repeat(${heatmapData.days.length}, 24px)`, gap: 2 }}>
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
                        const level = heatmapData.cells.get(`${m}-${d}`);
                        const bg = level ? `${riskColor(level)}${level === "critical" ? "88" : level === "high" ? "55" : level === "medium" ? "33" : "18"}` : `${T.border}`;
                        return <div key={d} style={{ width: 22, height: 22, borderRadius: 3, background: bg }} />;
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
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>Top Riscos</span>
              </div>
              {risk.top_risks.map((r, i) => (
                <div key={i} style={{ padding: "8px 16px", borderTop: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 12 }}>
                  <Pill color={riskColor(r.risk_level)}>{r.risk_level}</Pill>
                  <span style={{ fontSize: 12, fontFamily: T.mono, color: T.primary, flex: 1 }}>{r.sku}</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>{r.machine_id}</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>Slack: {r.slack}d</span>
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
              <Label>Total Atrasos</Label>
              <Num size={36} color={late.tardy_count > 0 ? T.red : T.green}>{late.tardy_count}</Num>
            </Card>
            <Card>
              <Label>Atraso Medio (dias)</Label>
              <Num size={36}>{late.avg_delay?.toFixed(1) ?? "0"}</Num>
            </Card>
            <Card>
              <Label>Pior Maquina</Label>
              <div style={{ marginTop: 8 }}>
                {late.worst_machine ? <Pill color={T.red}>{late.worst_machine}</Pill> : <span style={{ color: T.secondary, fontSize: 13 }}>-</span>}
              </div>
            </Card>
          </div>

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
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>SKU</th>
                  <th style={thStyle}>Maquina</th>
                  <th style={thStyle}>EDD</th>
                  <th style={thStyle}>Conclusao</th>
                  <th style={thStyle}>Atraso (d)</th>
                  <th style={thStyle}>Causa</th>
                  <th style={thStyle}>Sugestao</th>
                </tr>
              </thead>
              <tbody>
                {filteredAnalyses.map((a, i) => (
                  <tr key={i}>
                    <td style={tdStyle}>{a.sku}</td>
                    <td style={tdStyle}>{a.machine_id}</td>
                    <td style={tdStyle}>{a.edd}</td>
                    <td style={tdStyle}>{a.completion_day}</td>
                    <td style={{ ...tdStyle, color: T.red }}>{a.delay_days}</td>
                    <td style={tdStyle}><Pill color={T.orange}>{causeLabel(a.root_cause)}</Pill></td>
                    <td style={{ ...tdStyle, fontFamily: T.sans, fontSize: 11, color: T.secondary, maxWidth: 250 }}>{a.suggestion}</td>
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
              <Label>Dia Pico</Label>
              <Num size={28}>D{workforce.peak_day}</Num>
            </Card>
            <Card>
              <Label>Pico Operadores</Label>
              <Num size={28}>{workforce.peak_required}</Num>
            </Card>
            <Card>
              <Label>Media</Label>
              <Num size={28}>{workforce.avg_required.toFixed(1)}</Num>
            </Card>
            <Card>
              <Label>Dias com Deficit</Label>
              <Num size={28} color={workforce.deficit_days > 0 ? T.red : T.green}>{workforce.deficit_days}</Num>
            </Card>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Label>Tendencia:</Label>
            <Pill color={workforce.trend === "increasing" ? T.orange : workforce.trend === "decreasing" ? T.green : T.blue}>
              {workforce.trend === "increasing" ? "Crescente" : workforce.trend === "decreasing" ? "Decrescente" : "Estavel"}
            </Pill>
          </div>

          <Card style={{ padding: 0, overflow: "auto", maxHeight: 500 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>Dia</th>
                  <th style={thStyle}>Turno</th>
                  <th style={thStyle}>Grupo</th>
                  <th style={thStyle}>Necessarios</th>
                  <th style={thStyle}>Disponiveis</th>
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

      {/* ── Proposals ── */}
      {tab === "proposals" && late && (
        <>
          <Card>
            <Label style={{ marginBottom: 8 }}>Recomendacao Geral</Label>
            <div style={{ fontSize: 13, color: T.primary, lineHeight: 1.6 }}>{late.suggestion}</div>
          </Card>

          {late.analyses.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Label>Sugestoes por Atraso</Label>
              {late.analyses.map((a, i) => (
                <Card key={i} style={{ padding: "12px 16px" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontFamily: T.mono, fontWeight: 600, color: T.primary }}>{a.sku}</span>
                    <Pill color={T.orange}>{causeLabel(a.root_cause)}</Pill>
                    <span style={{ fontSize: 11, color: T.secondary }}>{a.machine_id} | +{a.delay_days}d</span>
                  </div>
                  <div style={{ fontSize: 12, color: T.secondary, lineHeight: 1.5 }}>{a.suggestion}</div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
