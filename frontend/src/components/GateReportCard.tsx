import type { GateProposal, GateReport } from "../api/types";
import { gateSummaryLines } from "../lib/gateApproval";
import { T } from "../theme/tokens";
import { Card } from "./ui/Card";
import { Pill } from "./ui/Pill";

function proposalMetricLine(proposal: GateProposal) {
  const before = proposal.before as Record<string, unknown> | undefined;
  const after = proposal.after_target as Record<string, unknown> | undefined;
  if (!before || !after) return null;
  const keys = [
    "tardy_count",
    "subcontract_dispatch_misses",
    "subcontract_dispatch_late_workdays",
    "otd",
    "otd_d",
    "setups",
    "setup_time_min",
    "earliness_avg_days",
    "setup_crew_overlaps",
  ];
  const parts = keys
    .filter((key) => key in before || key in after)
    .map((key) => `${key}: ${String(before[key] ?? "-")} → ${String(after[key] ?? "-")}`);
  return parts.length ? parts.join(" · ") : null;
}

function affectedLine(proposal: GateProposal) {
  const machines = proposal.affected_machines as string[] | undefined;
  const skus = proposal.affected_skus as string[] | undefined;
  const chunks = [];
  if (machines?.length) chunks.push(`máquinas ${machines.slice(0, 3).join(", ")}`);
  if (skus?.length) chunks.push(`Referências ${skus.slice(0, 3).join(", ")}`);
  return chunks.join(" · ");
}

/** "1 dia útil" / "N dias úteis"; "—" when the value is missing. */
function workdaysLabel(value: unknown): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n} ${n === 1 ? "dia útil" : "dias úteis"}`;
}

export function GateReportCard({ gate, activePlan = false }: { gate: GateReport; activePlan?: boolean }) {
  const metrics = gate.metrics ?? {};
  const feasibility = gate.feasibility
    && Array.isArray(gate.feasibility.binding_constraints)
    && Array.isArray(gate.feasibility.interventions)
    ? gate.feasibility
    : null;
  const jitWindowDetail = Array.isArray(gate.jit_window_detail) ? gate.jit_window_detail : [];
  const subcontractDispatchDetail = Array.isArray(gate.subcontract_dispatch_detail)
    ? gate.subcontract_dispatch_detail
    : [];
  const setupOverlapDetail = Array.isArray(gate.setup_overlap_detail) ? gate.setup_overlap_detail : [];
  const proposals = Array.isArray(gate.proposals) ? gate.proposals : [];
  const keptTransfers = gate.improvement?.tool_transfers?.items ?? [];
  const summaryLines = gateSummaryLines(gate);
  const statusColor = gate.apply_decision === "blocked" ? T.red : gate.status === "applicable"
    ? T.green
    : gate.status === "invalid_physics" || gate.status === "jit_window_blocked"
      ? T.red
      : T.orange;
  const candidateStatusLabel = gate.apply_decision === "blocked" && gate.status !== "invalid_physics" && gate.status !== "jit_window_blocked"
    ? "Resultado calculado · não aplicável"
    : gate.status === "applicable"
    ? "Aplicável"
    : gate.status === "jit_window_blocked"
      ? "Produções antecipadas bloqueiam aplicação"
      : gate.status === "invalid_physics"
        ? "Conflito físico"
        : "Requer aprovação";
  const statusLabel = activePlan
    ? gate.apply_decision === "blocked"
      ? "Plano ativo · necessita revisão"
      : gate.apply_decision === "approval_required"
        ? "Plano ativo · com riscos"
        : "Plano ativo"
    : candidateStatusLabel;
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <Pill color={statusColor}>{statusLabel}</Pill>
        {gate.improvement?.status === "partial" && (
          <span style={{ fontSize: 12, color: T.secondary }}>
            A melhoria automática parou antes de rever todas as hipóteses.
          </span>
        )}
      </div>
      {summaryLines.length > 0 && (
        <div data-testid="gate-summary" style={{ fontSize: 13, color: T.primary, lineHeight: 1.55, marginBottom: 8 }}>
          {summaryLines.map((line) => <p key={line} style={{ margin: "0 0 2px" }}>{line}</p>)}
        </div>
      )}
      {!activePlan && gate.apply_decision === "approval_required" && (
        <div style={{ padding: "8px 10px", borderRadius: 8, background: `${T.orange}10`, border: `1px solid ${T.orange}44`, marginBottom: 8, color: T.secondary, fontSize: 12, lineHeight: 1.5 }}>
          O resultado foi calculado e está disponível. Pode ser aplicado depois de o planeador rever o impacto e confirmar.
        </div>
      )}
      {!activePlan && gate.apply_decision === "blocked" && (
        <div style={{ padding: "8px 10px", borderRadius: 8, background: `${T.red}10`, border: `1px solid ${T.red}44`, marginBottom: 8, color: T.secondary, fontSize: 12, lineHeight: 1.5 }}>
          O resultado continua disponível para análise e para guardar como cenário. Apenas a substituição do plano ativo está indisponível.
        </div>
      )}
      {gate.status === "jit_window_blocked" && (
        <div style={{ padding: "8px 10px", borderRadius: 8, background: `${T.red}10`, border: `1px solid ${T.red}44`, marginBottom: 8, color: T.secondary, fontSize: 12, lineHeight: 1.5 }}>
          O plano contém produções antes da libertação simulada de material. A referência é a entrega ao cliente nos artigos normais e o envio para subcontratação nos artigos subcontratados.
        </div>
      )}
      {jitWindowDetail.length > 0 && (
        <details style={{ fontSize: 12, color: T.orange, lineHeight: 1.6, marginBottom: 8 }}>
          <summary style={{ cursor: "pointer", color: T.primary, fontWeight: 600 }}>
            Ver produções antecipadas ({jitWindowDetail.length})
          </summary>
          <div style={{ marginTop: 6 }}>
          {jitWindowDetail.slice(0, 3).map((violation, index) => (
            <div key={index}>
              {String(violation.lot_id)} · {String(violation.sku || violation.op_id)} · {String(violation.machine_id)} · início {String(violation.start_date || `D${String(violation.start_day)}`)} · referência {String(violation.material_reference_date || `D${String(violation.material_reference_day ?? violation.delivery_day)}`)} · {workdaysLabel(violation.excess_workdays)} antes do permitido
            </div>
          ))}
          </div>
        </details>
      )}
      {subcontractDispatchDetail.length > 0 && (
        <details style={{ fontSize: 12, color: T.orange, lineHeight: 1.6, marginBottom: 8 }}>
          <summary style={{ cursor: "pointer", color: T.primary, fontWeight: 600 }}>
            Ver envios para subcontratação em atraso ({subcontractDispatchDetail.length})
          </summary>
          <div style={{ marginTop: 6 }}>
            {subcontractDispatchDetail.slice(0, 5).map((item) => (
              <div key={`${item.lot_id}-${item.op_id}`}>
                {item.sku} · conclusão {item.completion_date ?? `D${item.completion_day}`} · envio necessário {item.subcontract_dispatch_date ?? `D${item.subcontract_dispatch_day}`} · {workdaysLabel(item.late_workdays)} de atraso
              </div>
            ))}
          </div>
        </details>
      )}
      {setupOverlapDetail.length > 0 && (
        <details style={{ fontSize: 12, color: T.red, lineHeight: 1.6, marginBottom: 8 }}>
          <summary style={{ cursor: "pointer", color: T.primary, fontWeight: 600 }}>
            Ver mudanças de ferramenta ao mesmo tempo com a mesma equipa ({setupOverlapDetail.length})
          </summary>
          <div style={{ marginTop: 6 }}>
            {setupOverlapDetail.slice(0, 3).map((violation, index) => (
              <div key={index}>
                D{String(violation.day_idx)} · {String(violation.machine_a)} / {String(violation.machine_b)} · {String(violation.tool_a)} / {String(violation.tool_b)}
              </div>
            ))}
          </div>
        </details>
      )}
      <details data-testid="gate-technical" style={{ marginTop: 8 }}>
        <summary style={{ cursor: "pointer", color: T.secondary, fontSize: 12, fontWeight: 600 }}>
          Detalhes técnicos
        </summary>
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6, fontSize: 11, color: T.secondary, lineHeight: 1.5 }}>
          <div style={{ fontFamily: T.mono }}>
            estado {gate.status} · decisão {gate.apply_decision}
            {gate.approval_reasons?.length ? ` · motivos ${gate.approval_reasons.join(", ")}` : ""}
          </div>
          <div style={{ fontFamily: T.mono }}>
            Material fora da janela {metrics.early_window_violations ?? 0} · envios sub. em atraso {metrics.subcontract_dispatch_misses ?? 0} · OTD-D {metrics.otd_d ?? 0}% · cobertura em falta {metrics.missing_lots ?? 0} lote(s) / {metrics.missing_qty ?? 0} pç · gémeas repetidas {metrics.duplicate_twin_output_qty ?? 0} pç · lotes em atraso {metrics.tardy_count ?? 0} · encomendas em atraso {metrics.orders_late ?? "—"}
          </div>
          {feasibility && !feasibility.strict_feasible && (
            <div>
              <div style={{ color: T.primary, fontWeight: 600 }}>
                Solver: {gate.solver_status ?? feasibility.solver_status}
                {feasibility.minimum_required_window_workdays_lower_bound != null
                  ? ` · limite inferior ${feasibility.minimum_required_window_workdays_lower_bound} dias úteis`
                  : ""}
              </div>
              {feasibility.binding_constraints.slice(0, 10).map((constraint, index) => (
                <div key={`${constraint.resource_type}-${constraint.resource_id}-${index}`} style={{ marginTop: 4 }}>
                  {constraint.resource_type} {constraint.resource_id} · D{constraint.from_day}–D{constraint.to_day} · défice {constraint.deficit_min.toFixed(0)} min
                </div>
              ))}
              {feasibility.interventions.length > 0 && (
                <div style={{ color: T.orange, marginTop: 5 }}>
                  Intervenções apenas propostas; nenhuma é aplicada automaticamente.
                </div>
              )}
            </div>
          )}
          {proposals.map((proposal) => {
            const line = proposalMetricLine(proposal);
            return line ? (
              <div key={proposal.id} style={{ fontFamily: T.mono, color: T.tertiary }}>{proposal.id}: {line}</div>
            ) : null;
          })}
          {keptTransfers.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: "pointer", color: T.primary, fontSize: 12, fontWeight: 600 }}>
                Transferências de ferramenta mantidas ({gate.improvement?.tool_transfers?.remaining ?? keptTransfers.length})
              </summary>
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                {keptTransfers.slice(0, 5).map((item) => (
                  <div key={item.key} style={{ fontSize: 12, color: T.secondary, lineHeight: 1.5 }}>
                    <span style={{ color: T.primary }}>
                      {item.tool_id} · {item.from_machine} → {item.to_machine} · D{item.day_idx}
                    </span>
                    {" · "}
                    {item.summary}
                  </div>
                ))}
              </div>
            </details>
          )}
          {proposals.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: "pointer", color: T.primary, fontSize: 12, fontWeight: 600 }}>
                Ver ações sugeridas ({proposals.length})
              </summary>
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
              {proposals.slice(0, 4).map((proposal) => (
                <div key={proposal.id} style={{ fontSize: 12, color: T.secondary, lineHeight: 1.5 }}>
                  <div style={{ color: T.primary }}>{proposal.description}</div>
                  <div>{proposal.expected_impact}</div>
                  {affectedLine(proposal) && <div style={{ color: T.tertiary }}>{affectedLine(proposal)}</div>}
                  {Array.isArray(proposal.rejection_reasons) && proposal.rejection_reasons.length > 0 && (
                    <div style={{ color: T.orange }}>
                      Rejeitar se: {(proposal.rejection_reasons as string[]).slice(0, 3).join(", ")}
                    </div>
                  )}
                </div>
              ))}
              </div>
            </details>
          )}
        </div>
      </details>
    </Card>
  );
}
