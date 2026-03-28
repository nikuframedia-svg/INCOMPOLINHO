import { useEffect, useMemo, useState } from "react";
import { T } from "../theme/tokens";
import { getStockSummary, getStockDetail } from "../api/endpoints";
import type { StockSummary, StockProjection, StockDayCompact } from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Dot } from "../components/ui/Dot";
import { Pill } from "../components/ui/Pill";

// ── Helpers ──────────────────────────────────────────────────

function fmtStock(v: number): string {
  if (v === 0) return "0";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 100_000) return `${sign}${(abs / 1000).toFixed(0)}k`;
  if (abs >= 10_000) return `${sign}${(abs / 1000).toFixed(1)}k`;
  return v.toLocaleString();
}

function fmtDate(iso: string): { short: string; dow: string } {
  // "2026-03-05" → "05-Mar", "Qua"
  const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const DOWS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"];
  try {
    const d = new Date(iso + "T12:00:00");
    return {
      short: `${String(d.getDate()).padStart(2, "0")}-${MONTHS[d.getMonth()]}`,
      dow: DOWS[d.getDay()],
    };
  } catch {
    return { short: iso, dow: "" };
  }
}

function cellBg(day: StockDayCompact, coverageDays: number): string {
  if (day.is_buffer) return `${T.blue}10`; // buffer day → subtle blue
  if (!day.workday) return T.border; // weekend/holiday → grey
  if (day.stock < 0) return `${T.red}30`; // ruptura → red
  if (coverageDays < 3 && coverageDays > 0 && day.stock > 0 && day.demand > 0)
    return `${T.orange}20`; // low coverage → yellow-ish
  return "transparent";
}

function cellColor(day: StockDayCompact): string {
  if (!day.workday) return T.tertiary;
  if (day.stock < 0) return T.red;
  if (day.stock === 0 && day.demand > 0) return T.orange;
  return T.primary;
}

const selectStyle: React.CSSProperties = {
  background: T.elevated,
  border: `0.5px solid ${T.border}`,
  borderRadius: 6,
  padding: "4px 8px",
  fontSize: 11,
  color: T.primary,
  fontFamily: T.mono,
  outline: "none",
  cursor: "pointer",
};

const toggleStyle = (active: boolean): React.CSSProperties => ({
  background: active ? T.elevated : "transparent",
  border: `0.5px solid ${active ? T.borderHover : T.border}`,
  borderRadius: 6,
  padding: "4px 10px",
  fontSize: 11,
  color: active ? T.primary : T.secondary,
  fontWeight: active ? 600 : 400,
  cursor: "pointer",
  fontFamily: "inherit",
});

// ── Cell width ───────────────────────────────────────────────

const CELL_W = 62;
const LABEL_W = 180;

// ── Main Component ───────────────────────────────────────────

export function StockPage() {
  const [data, setData] = useState<StockSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clientFilter, setClientFilter] = useState<string>("");
  const [machineFilter, setMachineFilter] = useState<string>("");
  const [riskOnly, setRiskOnly] = useState(false);
  const [hideNoDemand, setHideNoDemand] = useState(true);
  const [detail, setDetail] = useState<StockProjection | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    getStockSummary()
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  // Unique filter options
  const clients = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.map((s) => s.client))].sort();
  }, [data]);

  const machines = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.map((s) => s.machine).filter(Boolean))].sort();
  }, [data]);

  // Filtered & sorted rows
  const rows = useMemo(() => {
    if (!data) return [];
    let list = data;
    if (clientFilter) list = list.filter((s) => s.client === clientFilter);
    if (machineFilter) list = list.filter((s) => s.machine === machineFilter);
    if (riskOnly) list = list.filter((s) => s.stockout_day !== null);
    if (hideNoDemand) list = list.filter((s) => s.total_demand > 0);
    // Sort: rupturas first (by stockout_day ASC), then by SKU
    return [...list].sort((a, b) => {
      const aRisk = a.stockout_day ?? 9999;
      const bRisk = b.stockout_day ?? 9999;
      if (aRisk !== bRisk) return aRisk - bRisk;
      return a.sku.localeCompare(b.sku);
    });
  }, [data, clientFilter, machineFilter, riskOnly, hideNoDemand]);

  // Day columns from first row (all rows have same days structure)
  const dayColumns = useMemo(() => {
    if (!data || data.length === 0) return [];
    const first = data[0];
    if (!first.days) return [];
    return first.days.map((d) => {
      const fmt = fmtDate(d.date);
      return { day: d.day, date: d.date, short: fmt.short, dow: fmt.dow, workday: d.workday, isBuffer: d.is_buffer ?? false };
    });
  }, [data]);

  const riskCount = useMemo(() => {
    if (!data) return 0;
    return data.filter((s) => s.stockout_day !== null).length;
  }, [data]);

  const openDetail = async (sku: string) => {
    setDetailLoading(true);
    try {
      const res = await getStockDetail(sku);
      setDetail(res);
    } catch { /* ignore */ }
    setDetailLoading(false);
  };

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!data) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;
  if (data.length === 0) return <div style={{ color: T.secondary, padding: 24 }}>Sem dados de stock. Carrega um ISOP primeiro.</div>;

  const totalCount = hideNoDemand ? data.filter((s) => s.total_demand > 0).length : data.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Summary banner */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", background: T.card, borderRadius: 8, border: `0.5px solid ${T.border}` }}>
        <Dot color={riskCount > 0 ? T.red : T.green} size={8} />
        <span style={{ fontSize: 14, fontWeight: 500, color: T.primary }}>
          {totalCount} referencias.{" "}
          {riskCount > 0 ? (
            <span style={{ color: T.red }}>{riskCount} em risco de ruptura.</span>
          ) : (
            <span style={{ color: T.green }}>Todas cobertas.</span>
          )}
        </span>
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select value={clientFilter} onChange={(e) => setClientFilter(e.target.value)} style={selectStyle}>
          <option value="">Todos os clientes</option>
          {clients.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={machineFilter} onChange={(e) => setMachineFilter(e.target.value)} style={selectStyle}>
          <option value="">Todas as maquinas</option>
          {machines.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button onClick={() => setRiskOnly(!riskOnly)} style={toggleStyle(riskOnly)}>
          So rupturas
        </button>
        <button onClick={() => setHideNoDemand(!hideNoDemand)} style={toggleStyle(hideNoDemand)}>
          Esconder sem demanda
        </button>
        <span style={{ fontSize: 11, color: T.tertiary, marginLeft: 8 }}>
          {rows.length} de {hideNoDemand ? data.filter((s) => s.total_demand > 0).length : data.length} SKUs
        </span>
      </div>

      {/* Grid */}
      <div style={{
        overflow: "auto",
        maxHeight: "calc(100vh - 220px)",
        border: `0.5px solid ${T.border}`,
        borderRadius: 8,
        background: T.card,
      }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: `${LABEL_W}px repeat(${dayColumns.length}, ${CELL_W}px)`,
          width: LABEL_W + dayColumns.length * CELL_W,
        }}>
          {/* ── Header row: dates ── */}
          <div style={{
            position: "sticky",
            left: 0,
            top: 0,
            zIndex: 3,
            background: T.card,
            borderBottom: `1px solid ${T.border}`,
            borderRight: `1px solid ${T.border}`,
            padding: "6px 12px",
            fontSize: 10,
            fontWeight: 600,
            color: T.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}>
            SKU / DIA
          </div>
          {dayColumns.map((col) => (
            <div
              key={col.day}
              style={{
                position: "sticky",
                top: 0,
                zIndex: 2,
                background: col.isBuffer ? `${T.blue}08` : col.workday ? T.card : T.elevated,
                borderBottom: `1px solid ${T.border}`,
                padding: "4px 2px",
                textAlign: "center",
                fontSize: 9,
                fontFamily: T.mono,
                color: col.workday ? T.secondary : T.tertiary,
                lineHeight: 1.4,
              }}
            >
              <div style={{ fontWeight: 600 }}>{col.short}</div>
              <div>{col.dow}</div>
            </div>
          ))}

          {/* ── Data rows ── */}
          {rows.map((row) => {
            const hasRisk = row.stockout_day !== null;
            return (
              <div key={row.op_id} style={{ display: "contents" }}>
                {/* SKU label cell (sticky left) */}
                <div style={{
                  position: "sticky",
                  left: 0,
                  zIndex: 1,
                  background: hasRisk ? `color-mix(in srgb, ${T.red} 5%, ${T.card})` : T.card,
                  borderBottom: `1px solid ${T.border}`,
                  borderRight: `1px solid ${T.border}`,
                  padding: "6px 10px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 1,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {hasRisk && <Dot color={T.red} size={5} />}
                    <span
                      onClick={() => openDetail(row.sku)}
                      style={{ fontSize: 11, fontWeight: 600, color: T.blue, fontFamily: T.mono, cursor: "pointer" }}
                    >{row.sku}</span>
                  </div>
                  <div style={{ fontSize: 9, color: T.tertiary }}>
                    {row.client}
                    {row.machine && <span style={{ marginLeft: 6, color: T.tertiary }}>{row.machine}</span>}
                  </div>
                  {hasRisk && (
                    <Pill color={T.red}>esgota dia {row.stockout_day}</Pill>
                  )}
                </div>

                {/* Day cells */}
                {(row.days ?? []).map((day) => {
                  const bg = cellBg(day, row.coverage_days);
                  const color = cellColor(day);
                  return (
                    <div
                      key={day.day}
                      style={{
                        borderBottom: `1px solid ${T.border}`,
                        background: bg,
                        padding: "6px 2px",
                        textAlign: "center",
                        fontSize: 10,
                        fontFamily: T.mono,
                        color,
                        cursor: day.demand > 0 || day.produced > 0 ? "default" : undefined,
                        minHeight: 32,
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                      title={
                        !day.workday
                          ? "Fim-de-semana / Feriado"
                          : `Stock: ${day.stock.toLocaleString()}\nProcura: ${day.demand.toLocaleString()}\nProducao: ${day.produced.toLocaleString()}`
                      }
                    >
                      {!day.workday ? (
                        <span style={{ color: T.tertiary }}>—</span>
                      ) : (
                        <>
                          <span style={{ fontWeight: day.stock < 0 ? 700 : 400 }}>
                            {fmtStock(day.stock)}
                          </span>
                          {day.produced > 0 && (
                            <span style={{ fontSize: 8, color: T.green, marginTop: 1 }}>
                              +{fmtStock(day.produced)}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, alignItems: "center", padding: "4px 0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <div style={{ width: 12, height: 12, borderRadius: 2, background: `${T.red}30` }} />
          <span style={{ fontSize: 10, color: T.tertiary }}>Ruptura</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <div style={{ width: 12, height: 12, borderRadius: 2, background: `${T.orange}20` }} />
          <span style={{ fontSize: 10, color: T.tertiary }}>Cobertura baixa</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <div style={{ width: 12, height: 12, borderRadius: 2, background: T.border }} />
          <span style={{ fontSize: 10, color: T.tertiary }}>Nao util</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <div style={{ width: 12, height: 12, borderRadius: 2, background: `${T.blue}10` }} />
          <span style={{ fontSize: 10, color: T.tertiary }}>Buffer</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 10, color: T.green }}>+N</span>
          <span style={{ fontSize: 10, color: T.tertiary }}>Producao</span>
        </div>
      </div>

      {/* Detail Modal */}
      {(detail || detailLoading) && (
        <div
          onClick={() => { setDetail(null); setDetailLoading(false); }}
          style={{
            position: "fixed", inset: 0, zIndex: 100,
            background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          <Card
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
            style={{ width: 600, maxHeight: "80vh", overflow: "auto", padding: 20 }}
          >
            {detailLoading && !detail ? (
              <div style={{ color: T.secondary, fontSize: 13 }}>A carregar...</div>
            ) : detail ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div>
                    <span style={{ fontSize: 16, fontWeight: 700, fontFamily: T.mono, color: T.primary }}>{detail.sku}</span>
                    <span style={{ fontSize: 12, color: T.secondary, marginLeft: 12 }}>{detail.client} | {detail.machine}</span>
                  </div>
                  <button onClick={() => setDetail(null)} style={{ background: "none", border: "none", color: T.secondary, cursor: "pointer", fontSize: 18 }}>x</button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 16 }}>
                  <div><Label>Total Demand</Label><div style={{ fontFamily: T.mono, fontSize: 14, color: T.primary, marginTop: 2 }}>{detail.total_demand.toLocaleString()}</div></div>
                  <div><Label>Stock Inicial</Label><div style={{ fontFamily: T.mono, fontSize: 14, color: T.primary, marginTop: 2 }}>{detail.initial_stock.toLocaleString()}</div></div>
                  <div><Label>Cobertura</Label><div style={{ fontFamily: T.mono, fontSize: 14, color: T.primary, marginTop: 2 }}>{detail.coverage_days}d</div></div>
                  <div><Label>Ruptura</Label><div style={{ fontFamily: T.mono, fontSize: 14, color: detail.stockout_day !== null ? T.red : T.green, marginTop: 2 }}>{detail.stockout_day !== null ? `D${detail.stockout_day}` : "Nao"}</div></div>
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", color: T.tertiary, padding: "4px 6px", borderBottom: `1px solid ${T.border}`, fontSize: 10 }}>Dia</th>
                      <th style={{ textAlign: "right", color: T.tertiary, padding: "4px 6px", borderBottom: `1px solid ${T.border}`, fontSize: 10 }}>Procura</th>
                      <th style={{ textAlign: "right", color: T.tertiary, padding: "4px 6px", borderBottom: `1px solid ${T.border}`, fontSize: 10 }}>Producao</th>
                      <th style={{ textAlign: "right", color: T.tertiary, padding: "4px 6px", borderBottom: `1px solid ${T.border}`, fontSize: 10 }}>Stock</th>
                      <th style={{ textAlign: "left", color: T.tertiary, padding: "4px 6px", borderBottom: `1px solid ${T.border}`, fontSize: 10 }}>Maquina</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.days.map((d) => (
                      <tr key={d.day_idx}>
                        <td style={{ padding: "3px 6px", fontFamily: T.mono, color: d.is_buffer ? T.blue : T.secondary, borderBottom: `1px solid ${T.border}` }}>{d.is_buffer ? `B${d.day_idx}` : `D${d.day_idx}`}</td>
                        <td style={{ padding: "3px 6px", fontFamily: T.mono, textAlign: "right", color: d.demand > 0 ? T.primary : T.tertiary, borderBottom: `1px solid ${T.border}` }}>{d.demand > 0 ? d.demand.toLocaleString() : "-"}</td>
                        <td style={{ padding: "3px 6px", fontFamily: T.mono, textAlign: "right", color: d.produced > 0 ? T.green : T.tertiary, borderBottom: `1px solid ${T.border}` }}>{d.produced > 0 ? d.produced.toLocaleString() : "-"}</td>
                        <td style={{ padding: "3px 6px", fontFamily: T.mono, textAlign: "right", color: d.stock < 0 ? T.red : T.primary, fontWeight: d.stock < 0 ? 600 : 400, borderBottom: `1px solid ${T.border}` }}>{d.stock.toLocaleString()}</td>
                        <td style={{ padding: "3px 6px", fontFamily: T.mono, color: T.tertiary, borderBottom: `1px solid ${T.border}` }}>{d.machine ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : null}
          </Card>
        </div>
      )}
    </div>
  );
}
