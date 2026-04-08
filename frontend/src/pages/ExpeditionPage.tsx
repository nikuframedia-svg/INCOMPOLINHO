import { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { getExpedition, getOrders, getCoverage } from "../api/endpoints";
import type { ExpeditionKPIs, ClientOrders, CoverageAudit } from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Num } from "../components/ui/Num";
import { Dot } from "../components/ui/Dot";
import { Pill } from "../components/ui/Pill";

const thStyle: React.CSSProperties = {
  fontSize: 11, color: T.tertiary, fontWeight: 500, textAlign: "left",
  padding: "8px 12px", borderBottom: `1px solid ${T.border}`,
  textTransform: "uppercase", letterSpacing: "0.04em",
};

const tdStyle: React.CSSProperties = {
  fontSize: 12, color: T.primary, padding: "6px 12px",
  borderBottom: `1px solid ${T.border}`, fontFamily: T.mono,
};

const statusColor = (status: string) => {
  if (status === "ready") return T.green;
  if (status === "partial" || status === "in_production") return T.orange;
  return T.red;
};

export function ExpeditionPage() {
  const [expedition, setExpedition] = useState<ExpeditionKPIs | null>(null);
  const [orders, setOrders] = useState<ClientOrders[] | null>(null);
  const [coverage, setCoverage] = useState<CoverageAudit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"timeline" | "clients">("timeline");
  const [expandedDay, setExpandedDay] = useState<number | null>(null);
  const [expandedClient, setExpandedClient] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getExpedition(), getOrders(), getCoverage()])
      .then(([e, o, c]) => { setExpedition(e); setOrders(o); setCoverage(c); })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!expedition) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const fillColor = expedition.fill_rate >= 95 ? T.green : expedition.fill_rate >= 80 ? T.orange : T.red;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* KPI strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        <Card>
          <Label>Fill Rate</Label>
          <Num size={36} color={fillColor}>{expedition.fill_rate.toFixed(1)}%</Num>
        </Card>
        <Card>
          <Label>Em Risco (5 dias)</Label>
          <Num size={36} color={expedition.at_risk_count > 0 ? T.red : T.green}>{expedition.at_risk_count}</Num>
        </Card>
        <Card>
          <Label>Cobertura Global</Label>
          <Num size={36} color={coverage && coverage.overall_coverage_pct >= 95 ? T.green : T.orange}>
            {coverage?.overall_coverage_pct.toFixed(1) ?? "-"}%
          </Num>
        </Card>
      </div>

      {/* View toggle */}
      <div style={{ display: "flex", gap: 4 }}>
        {(["timeline", "clients"] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            style={{
              background: view === v ? T.elevated : "transparent",
              border: `1px solid ${view === v ? T.borderHover : T.border}`,
              color: view === v ? T.primary : T.secondary,
              borderRadius: 8, padding: "5px 12px", cursor: "pointer",
              fontSize: 12, fontWeight: view === v ? 600 : 400, fontFamily: "inherit",
            }}
          >
            {v === "timeline" ? "Timeline" : "Clientes"}
          </button>
        ))}
      </div>

      {/* ── Timeline view ── */}
      {view === "timeline" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {expedition.days.map((day) => {
            const isExpanded = expandedDay === day.day_idx;
            return (
              <Card key={day.day_idx} style={{ padding: 0, cursor: "pointer" }} onClick={() => setExpandedDay(isExpanded ? null : day.day_idx)}>
                <div style={{ padding: "10px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: T.mono }}>D{day.day_idx}</span>
                    <span style={{ fontSize: 11, color: T.secondary }}>{day.date}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.green} size={6} /><span style={{ fontSize: 11, color: T.secondary }}>{day.ready}</span>
                    </span>
                    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.orange} size={6} /><span style={{ fontSize: 11, color: T.secondary }}>{day.partial}</span>
                    </span>
                    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.red} size={6} /><span style={{ fontSize: 11, color: T.secondary }}>{day.not_planned}</span>
                    </span>
                    <span style={{ fontSize: 11, color: T.tertiary }}>Total: {day.total}</span>
                    <span style={{ fontSize: 11, color: T.tertiary }}>{isExpanded ? "\u25B2" : "\u25BC"}</span>
                  </div>
                </div>

                {isExpanded && day.entries.length > 0 && (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        <th style={thStyle}>Cliente</th>
                        <th style={thStyle}>SKU</th>
                        <th style={thStyle}>Qtd</th>
                        <th style={thStyle}>Produzido</th>
                        <th style={thStyle}>Falha</th>
                        <th style={thStyle}>Status</th>
                        <th style={thStyle}>Cobertura</th>
                      </tr>
                    </thead>
                    <tbody>
                      {day.entries.map((e, i) => (
                        <tr key={i}>
                          <td style={{ ...tdStyle, fontFamily: T.sans }}>{e.client}</td>
                          <td style={tdStyle}>{e.sku}</td>
                          <td style={tdStyle}>{e.order_qty.toLocaleString()}</td>
                          <td style={tdStyle}>{e.produced_qty.toLocaleString()}</td>
                          <td style={{ ...tdStyle, color: e.shortfall > 0 ? T.red : T.green }}>{e.shortfall.toLocaleString()}</td>
                          <td style={tdStyle}><Dot color={statusColor(e.status)} size={8} /></td>
                          <td style={tdStyle}>{e.coverage_pct.toFixed(0)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* ── Client view ── */}
      {view === "clients" && orders && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {orders.map((co) => {
            const isExpanded = expandedClient === co.client;
            return (
              <Card key={co.client} style={{ padding: 0, cursor: "pointer" }} onClick={() => setExpandedClient(isExpanded ? null : co.client)}>
                <div style={{ padding: "10px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>{co.client}</span>
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <span style={{ fontSize: 11, color: T.green, fontFamily: T.mono }}>{co.total_ready}/{co.total_orders} prontos</span>
                    <span style={{ fontSize: 11, color: T.tertiary }}>{isExpanded ? "\u25B2" : "\u25BC"}</span>
                  </div>
                </div>

                {isExpanded && (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        <th style={thStyle}>SKU</th>
                        <th style={thStyle}>Qtd</th>
                        <th style={thStyle}>Dia Entrega</th>
                        <th style={thStyle}>Status</th>
                        <th style={thStyle}>Dias Antecipacao</th>
                        <th style={thStyle}>Maquina</th>
                      </tr>
                    </thead>
                    <tbody>
                      {co.orders.map((o, i) => (
                        <tr key={i}>
                          <td style={tdStyle}>{o.sku}</td>
                          <td style={tdStyle}>{o.order_qty.toLocaleString()}</td>
                          <td style={tdStyle}>D{o.delivery_day}</td>
                          <td style={tdStyle}><Pill color={statusColor(o.status)}>{o.status}</Pill></td>
                          <td style={{ ...tdStyle, color: (o.days_early ?? 0) >= 0 ? T.green : T.red }}>
                            {o.days_early !== null ? `${o.days_early >= 0 ? "+" : ""}${o.days_early}` : "-"}
                          </td>
                          <td style={tdStyle}>{o.production_machine ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            );
          })}

          {/* Coverage section */}
          {coverage && coverage.clients.length > 0 && (
            <>
              <Label style={{ marginTop: 8 }}>Cobertura por Cliente</Label>
              <Card style={{ padding: 0, overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={thStyle}>Cliente</th>
                      <th style={thStyle}>Encomendas</th>
                      <th style={thStyle}>Cobertas</th>
                      <th style={thStyle}>Cobertura %</th>
                      <th style={thStyle}>Em Risco</th>
                      <th style={thStyle}>Pior SKU</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coverage.clients.map((c) => (
                      <tr key={c.client}>
                        <td style={{ ...tdStyle, fontFamily: T.sans }}>{c.client}</td>
                        <td style={tdStyle}>{c.total_orders}</td>
                        <td style={tdStyle}>{c.covered_orders}</td>
                        <td style={{ ...tdStyle, color: c.coverage_pct >= 100 ? T.green : T.orange }}>{c.coverage_pct.toFixed(0)}%</td>
                        <td style={{ ...tdStyle, color: c.at_risk_orders > 0 ? T.red : T.green }}>{c.at_risk_orders}</td>
                        <td style={tdStyle}>{c.worst_sku ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </>
          )}
        </div>
      )}
    </div>
  );
}
