import { getLateDeliveries } from "../api/endpoints";
import { usePlanQuery } from "../hooks/usePlanQuery";
import { T } from "../theme/tokens";
import { Label } from "./ui/Label";
import { Modal } from "./ui/Modal";
import { Pill } from "./ui/Pill";

function causeLabel(cause: string) {
  const labels: Record<string, string> = {
    capacity: "Capacidade",
    setup_overhead: "Setup",
    priority_conflict: "Prioridade",
    lead_time: "Lead time",
    tool_contention: "Ferramenta",
  };
  return labels[cause] ?? cause;
}

const thStyle: React.CSSProperties = {
  padding: "8px 10px",
  textAlign: "left",
  fontSize: 10,
  textTransform: "uppercase",
  color: T.tertiary,
  borderBottom: `1px solid ${T.border}`,
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "9px 10px",
  fontSize: 12,
  color: T.primary,
  borderBottom: `1px solid ${T.border}`,
  fontFamily: T.mono,
  verticalAlign: "top",
};

export function LateDeliveriesModal({ onClose }: { onClose: () => void }) {
  const { data: late, error } = usePlanQuery("late-deliveries", getLateDeliveries);

  return (
    <Modal title="Detalhe dos atrasos" onClose={onClose} width={860}>
      {error && <div style={{ fontSize: 12, color: T.red }}>{error}</div>}
      {!error && !late && <div style={{ fontSize: 12, color: T.secondary }}>A carregar...</div>}
      {late && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap" }}>
            <div>
              <Label>Total</Label>
              <div style={{ fontSize: 24, fontWeight: 700, color: late.tardy_count > 0 ? T.red : T.green, fontFamily: T.mono }}>
                {late.tardy_count}
              </div>
            </div>
            <div>
              <Label>Atraso médio</Label>
              <div style={{ fontSize: 24, fontWeight: 700, color: T.primary, fontFamily: T.mono }}>
                {late.avg_delay.toFixed(1)}d
              </div>
            </div>
            {late.worst_machine && <Pill color={T.orange}>{late.worst_machine}</Pill>}
          </div>

          <div style={{ fontSize: 12, color: T.secondary, lineHeight: 1.5 }}>{late.suggestion}</div>

          <div style={{ overflow: "auto", border: `1px solid ${T.border}`, borderRadius: 8 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
              <thead>
                <tr>
                  <th style={thStyle}>SKU</th>
                  <th style={thStyle}>Máquina</th>
                  <th style={thStyle}>Entrega cliente</th>
                  <th style={thStyle}>Saída fábrica</th>
                  <th style={thStyle}>Pronto cliente</th>
                  <th style={thStyle}>Atraso</th>
                  <th style={thStyle}>Causa</th>
                  <th style={thStyle}>Explicação</th>
                </tr>
              </thead>
              <tbody>
                {late.analyses.map((a) => (
                  <tr key={a.lot_id}>
                    <td style={tdStyle}>{a.sku}</td>
                    <td style={tdStyle}>{a.machine_id}</td>
                    <td style={tdStyle}>D{a.edd}</td>
                    <td style={tdStyle}>D{a.completion_day}</td>
                    <td style={tdStyle}>D{a.customer_ready_day ?? a.completion_day}</td>
                    <td style={{ ...tdStyle, color: T.red, fontWeight: 700 }}>+{a.delay_days}d</td>
                    <td style={tdStyle}><Pill color={T.orange}>{causeLabel(a.root_cause)}</Pill></td>
                    <td style={{ ...tdStyle, fontFamily: T.sans, color: T.secondary, minWidth: 260 }}>
                      {a.explanation}
                    </td>
                  </tr>
                ))}
                {late.analyses.length === 0 && (
                  <tr>
                    <td colSpan={8} style={{ ...tdStyle, fontFamily: T.sans, color: T.secondary }}>
                      Sem lotes em atraso.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
