import { useMemo, useState } from "react";
import type { GateProposal, GateReport } from "../api/types";
import type { JitViolationDetail, JitWindowAnalysis } from "../lib/jitAnalysis";
import { T } from "../theme/tokens";

const EMPTY_VIOLATIONS: JitViolationDetail[] = [];

function shortDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return match ? `${match[3]}/${match[2]}` : iso;
}

const controlStyle: React.CSSProperties = {
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  background: T.card,
  color: T.primary,
  padding: "7px 10px",
  fontSize: 11,
  outline: "none",
};

function metricValue(metrics: Record<string, number> | undefined, key: string, fallback = 0): number {
  const value = metrics?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function proposalMetricLine(proposal: GateProposal) {
  const before = proposal.before as Record<string, unknown> | undefined;
  const after = proposal.after_target as Record<string, unknown> | undefined;
  if (!before || !after) return null;
  const keys = ["early_window_violations", "subcontract_dispatch_misses", "otd_d", "tardy_count"];
  const parts = keys
    .filter((key) => key in before || key in after)
    .map((key) => `${key}: ${String(before[key] ?? "-")} → ${String(after[key] ?? "-")}`);
  return parts.length ? parts.join(" · ") : null;
}

export function JitViolationPanel({
  analysis,
  gate,
  onFocus,
}: {
  analysis: JitWindowAnalysis | null;
  gate?: GateReport | null;
  onFocus: (violation: JitViolationDetail) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [machine, setMachine] = useState("todas");
  const violations = analysis?.violations ?? EMPTY_VIOLATIONS;
  const machines = useMemo(
    () => [...new Set(violations.map((item) => item.machine_id))].sort(),
    [violations],
  );
  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return violations.filter((item) => {
      const matchesMachine = machine === "todas" || item.machine_id === machine;
      const matchesQuery = !normalized || [
        item.lot_id,
        item.sku,
        item.tool_id,
        item.machine_id,
        item.reason,
      ].some((value) => value.toLowerCase().includes(normalized));
      return matchesMachine && matchesQuery;
    });
  }, [machine, query, violations]);

  const ready = analysis !== null;
  const compliant = ready && violations.length === 0;
  const color = compliant ? T.green : T.orange;
  const worstExcess = Math.max(...violations.map((item) => item.excess_workdays), 0);
  const metrics = gate?.metrics;
  const proposals = Array.isArray(gate?.proposals) ? gate.proposals : [];

  return (
    <section
      style={{
        border: `1px solid ${color}55`,
        background: `${color}0B`,
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => ready && violations.length > 0 && setOpen((value) => !value)}
        aria-expanded={open}
        style={{
          width: "100%",
          border: 0,
          background: "transparent",
          padding: "11px 14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 14,
          flexWrap: "wrap",
          color,
          cursor: ready && violations.length > 0 ? "pointer" : "default",
          fontFamily: "inherit",
          textAlign: "left",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12, fontWeight: 700 }}>
          <span aria-hidden="true" style={{ fontFamily: T.mono, fontSize: 11 }}>
            {open ? "−" : violations.length > 0 ? "+" : "✓"}
          </span>
          {!ready
            ? "A verificar a antecipação das produções…"
            : compliant
              ? "Libertação de material: nenhuma produção fora da janela dos cinco dias úteis"
              : `Produções antecipadas: ${violations.length} começaram cedo demais`}
        </span>
        {ready && (
          <span style={{ display: "flex", alignItems: "center", gap: 12, color: T.secondary, fontSize: 11 }}>
            <span style={{ fontFamily: T.mono }}>
              pior caso: {worstExcess} dias úteis de antecedência além do permitido
            </span>
            {violations.length > 0 && (
              <span style={{ color, fontWeight: 650 }}>{open ? "Fechar lista" : "Ver produções"}</span>
            )}
          </span>
        )}
      </button>

      {open && (
        <div style={{ borderTop: `1px solid ${color}33`, background: T.card }}>
          <div
            style={{
              padding: "12px 14px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 10,
              flexWrap: "wrap",
              borderBottom: `1px solid ${T.border}`,
            }}
          >
          <div>
              <div style={{ color: T.primary, fontSize: 12, fontWeight: 650 }}>
                Produções planeadas antes da libertação simulada de material
              </div>
              <div style={{ color: T.tertiary, fontSize: 10, marginTop: 2 }}>
                A janela começa cinco dias úteis antes da entrega ao cliente nos artigos normais e cinco
                dias úteis antes do envio para subcontratação nos artigos subcontratados.
              </div>
              {gate?.status === "jit_window_blocked" && (
                <details style={{ marginTop: 6 }}>
                  <summary style={{ cursor: "pointer", color: T.secondary, fontSize: 10, fontWeight: 600 }}>
                    Detalhes técnicos
                  </summary>
                  <div style={{ color: T.secondary, fontSize: 10, marginTop: 4, fontFamily: T.mono }}>
                    Material fora da janela {metricValue(metrics, "early_window_violations")} · envios sub. em atraso {metricValue(metrics, "subcontract_dispatch_misses")} · OTD-D {metricValue(metrics, "otd_d")}% · cobertura em falta {metricValue(metrics, "missing_lots")} lote(s) / {metricValue(metrics, "missing_qty")} pç · gémeas repetidas {metricValue(metrics, "duplicate_twin_output_qty")} pç · lotes em atraso {metricValue(metrics, "tardy_count")}
                  </div>
                </details>
              )}
            </div>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Procurar artigo ou ferramenta…"
                aria-label="Filtrar exceções JIT"
                style={{ ...controlStyle, width: 190 }}
              />
              <select
                value={machine}
                onChange={(event) => setMachine(event.target.value)}
                aria-label="Filtrar exceções por máquina"
                style={controlStyle}
              >
                <option value="todas">Todas as máquinas</option>
                {machines.map((id) => <option key={id} value={id}>{id}</option>)}
              </select>
              <span style={{ ...controlStyle, borderColor: "transparent", color: T.secondary }}>
                A mostrar {visible.length} de {violations.length}
              </span>
            </div>
          </div>

          {gate?.status === "jit_window_blocked" && (
            <div style={{ margin: "10px 14px 0", padding: "8px 10px", borderRadius: 8, background: `${T.red}10`, border: `1px solid ${T.red}44`, color: T.secondary, fontSize: 11, lineHeight: 1.5 }}>
              O plano contém produções anteriores à data simulada de libertação de material e não pode ser aplicado até ser recalculado ou a disponibilidade ser corrigida.
            </div>
          )}

          <div style={{ overflowX: "auto", maxHeight: 480, overflowY: "auto" }}>
            <table style={{ width: "100%", minWidth: 1120, borderCollapse: "collapse", fontSize: 10 }}>
              <thead style={{ position: "sticky", top: 0, zIndex: 1, background: T.elevated }}>
                <tr>
                  {["Artigo / produção", "Onde", "Começou", "Referência material", "Entrega cliente", "Só podia começar", "Antecedência", "Dias cedo a mais", "Porque aconteceu", ""].map((label) => (
                    <th
                      key={label}
                      style={{
                        padding: "8px 10px",
                        borderBottom: `1px solid ${T.border}`,
                        color: T.secondary,
                        fontWeight: 650,
                        textAlign: "left",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.lot_id} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ padding: "9px 10px", verticalAlign: "top" }}>
                      <div style={{ color: T.primary, fontFamily: T.mono, fontWeight: 700 }}>{item.sku}</div>
                      <div style={{ color: T.secondary, marginTop: 3 }}>
                        {item.qty.toLocaleString("pt-PT")} peças{item.is_twin ? " · produção gémea" : ""}
                      </div>
                      <div style={{ color: T.tertiary, fontFamily: T.mono, marginTop: 3, maxWidth: 260, overflowWrap: "anywhere" }}>
                        Lote {item.lot_id}
                      </div>
                    </td>
                    <td style={{ padding: "9px 10px", verticalAlign: "top", whiteSpace: "nowrap" }}>
                      <div style={{ color: T.primary }}>Máquina <span style={{ fontFamily: T.mono, fontWeight: 650 }}>{item.machine_id}</span></div>
                      <div style={{ color: T.tertiary, marginTop: 3 }}>Ferramenta <span style={{ fontFamily: T.mono }}>{item.tool_id}</span></div>
                    </td>
                    <td title={`Dia interno D${item.start_day}`} style={{ padding: "9px 10px", verticalAlign: "top", fontFamily: T.mono, whiteSpace: "nowrap" }}>
                      {shortDate(item.start_date)}
                    </td>
                    <td title={`Dia interno D${item.material_reference_day}`} style={{ padding: "9px 10px", verticalAlign: "top", fontFamily: T.mono, whiteSpace: "nowrap" }}>
                      {shortDate(item.material_reference_date)}
                      <div style={{ color: T.tertiary, marginTop: 3, fontFamily: T.sans }}>
                        {item.material_reference_kind === "subcontract_dispatch" ? "envio sub." : "entrega"}
                      </div>
                    </td>
                    <td title={`Dia interno D${item.customer_delivery_day}`} style={{ padding: "9px 10px", verticalAlign: "top", fontFamily: T.mono, whiteSpace: "nowrap" }}>
                      {shortDate(item.customer_delivery_date)}
                    </td>
                    <td title={`Dia interno D${item.earliest_allowed_start_day}`} style={{ padding: "9px 10px", verticalAlign: "top", fontFamily: T.mono, whiteSpace: "nowrap" }}>
                      {shortDate(item.earliest_allowed_start_date)}
                    </td>
                    <td style={{ padding: "9px 10px", verticalAlign: "top", fontFamily: T.mono, whiteSpace: "nowrap" }}>
                      {item.anticipation_workdays} dias úteis
                    </td>
                    <td style={{ padding: "9px 10px", verticalAlign: "top" }}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "3px 7px",
                          borderRadius: 6,
                          background: `${T.red}14`,
                          border: `1px solid ${T.red}33`,
                          color: T.red,
                          fontFamily: T.mono,
                          fontWeight: 750,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.increment_workdays} dias úteis
                      </span>
                    </td>
                    <td style={{ padding: "9px 10px", verticalAlign: "top", color: T.secondary, lineHeight: 1.45, minWidth: 290 }}>
                      {item.reason}
                    </td>
                    <td style={{ padding: "9px 10px", verticalAlign: "top" }}>
                      <button
                        type="button"
                        onClick={() => onFocus(item)}
                        style={{
                          border: `1px solid ${T.border}`,
                          borderRadius: 7,
                          background: T.card,
                          color: T.blue,
                          padding: "5px 8px",
                          fontSize: 10,
                          cursor: "pointer",
                          whiteSpace: "nowrap",
                        }}
                      >
                        Abrir no plano
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {proposals.length > 0 && (
            <details style={{ margin: "10px 14px 12px", fontSize: 11, color: T.secondary, lineHeight: 1.5 }}>
              <summary style={{ cursor: "pointer", color: T.primary, fontWeight: 650 }}>
                Ver ações sugeridas ({proposals.length})
              </summary>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
                {proposals.slice(0, 4).map((proposal) => (
                  <div key={proposal.id} style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
                    <div style={{ color: T.primary, fontWeight: 650 }}>{proposal.description}</div>
                    <div>{proposal.expected_impact}</div>
                    {proposalMetricLine(proposal) && (
                      <div style={{ color: T.tertiary, fontFamily: T.mono }}>{proposalMetricLine(proposal)}</div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
