import { T } from "../theme/tokens";
import { getConfig } from "../api/endpoints";
import type { FactoryConfig } from "../api/types";
import { usePlanQuery } from "../hooks/usePlanQuery";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Dot } from "../components/ui/Dot";

interface SchedulerRule {
  id: string;
  categoria: string;
  descricao: string;
  valor: string;
  activo: boolean;
}

function buildRules(config: FactoryConfig): SchedulerRule[] {
  return [
    { id: "F01", categoria: "Leis físicas", descricao: "Máquina não produz dois segmentos ao mesmo tempo", valor: "machine_overlaps = 0", activo: true },
    { id: "F02", categoria: "Leis físicas", descricao: "Ferramenta não está em duas máquinas ao mesmo tempo", valor: "tool_conflicts = 0", activo: true },
    { id: "F03", categoria: "Leis físicas", descricao: "Cada grupo tem a sua equipa de setup; dentro do grupo não há sobreposição", valor: Object.entries(config.setup_crews_by_group).map(([group, count]) => `${group}=${count}`).join(" · "), activo: Object.values(config.setup_crews_by_group).every((count) => count >= 1) },
    { id: "F04", categoria: "Leis físicas", descricao: "Máquina ou ferramenta bloqueada não produz", valor: "blocked = 0", activo: true },
    { id: "F05", categoria: "Leis físicas", descricao: "Capacidade diária por máquina não é excedida", valor: `${config.day_capacity_min} min`, activo: true },
    { id: "E01", categoria: "Objetivos", descricao: "Maximizar primeiro o número de encomendas entregues a tempo", valor: "Prioridade 1", activo: true },
    { id: "E02", categoria: "Objetivos", descricao: "Depois maximizar a quantidade entregue a tempo e minimizar o atraso", valor: "Prioridade 2", activo: true },
    { id: "J01", categoria: "Material", descricao: "Libertar material cinco dias úteis antes da entrega ao cliente; nos artigos subcontratados, cinco dias úteis antes do envio ao fornecedor", valor: "Obrigatório", activo: true },
    { id: "J02", categoria: "Material", descricao: "Bloquear qualquer produção iniciada antes da respetiva libertação simulada", valor: "Gate bloqueante", activo: true },
    { id: "J03", categoria: "Antecipação", descricao: "Produzir no primeiro intervalo viável depois da libertação de material, em qualquer máquina elegível", valor: "O mais cedo possível", activo: true },
    { id: "J04", categoria: "Antecipação (alerta)", descricao: `Tentar limitar cada produção a ${config.max_run_days} dias úteis; permitir exceção necessária`, valor: `≤ ${config.max_run_days} dias`, activo: true },
    { id: "S01", categoria: "Subcontratação", descricao: "Concluir a produção antes da data planeada de envio ao subcontratante", valor: "Gate de aprovação", activo: true },
    { id: "S02", categoria: "Subcontratação", descricao: "Manter a entrega ao cliente como compromisso e KPI, acrescentando o prazo externo do fornecedor à conclusão na fábrica", valor: "OTD cliente", activo: true },
    { id: "B01", categoria: "Negócio", descricao: "Eco lot hard", valor: String(config.eco_lot_mode), activo: true },
    { id: "B02", categoria: "Negócio", descricao: "Gémeas produzem em simultâneo", valor: `${config.twins.length} regras`, activo: true },
    { id: "P01", categoria: "Preferências", descricao: "Sem perdas de entrega, preferir o início de produção mais cedo, lote a lote pela prioridade comercial (prazo, rutura, prioridade)", valor: "Antecipação primeiro", activo: true },
    { id: "P02", categoria: "Preferências", descricao: "Com a mesma antecipação, preferir menos setups e menos minutos de setup; um setup extra nunca impede uma antecipação", valor: "Desempate", activo: true },
    { id: "P03", categoria: "Preferências", descricao: "Depois, preferir menos transferências de ferramenta e menos alterações ao plano", valor: "Desempate", activo: true },
    { id: "P04", categoria: "Sequenciação", descricao: "No plano inicial, agrupar campanhas da mesma ferramenta com prazos dentro da janela", valor: `${config.campaign_window} dias de prazo`, activo: true },
    { id: "P05", categoria: "Alerta", descricao: "Avisar quando a antecipação média excede o alvo; é só um aviso, não limita o plano", valor: `${config.jit_earliness_target ?? 5.5} dias`, activo: true },
  ];
}

const thStyle: React.CSSProperties = {
  fontSize: 11, color: T.tertiary, fontWeight: 500, textAlign: "left",
  padding: "8px 12px", borderBottom: `1px solid ${T.border}`,
  textTransform: "uppercase", letterSpacing: "0.04em",
};

const tdStyle: React.CSSProperties = {
  fontSize: 12, color: T.primary, padding: "6px 12px",
  borderBottom: `1px solid ${T.border}`,
};

export function RulesPage() {
  const { data: config, error } = usePlanQuery("rules", getConfig);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!config) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const rules = buildRules(config);
  const categorias = [...new Set(rules.map((r) => r.categoria))];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, color: T.secondary }}>
        {rules.length} regras ativas. Conflitos físicos, quantidades inválidas e produção antes da libertação de material bloqueiam; atrasos de entrega ou de envio exigem aprovação explícita.
      </div>

      {categorias.map((cat) => (
        <Card key={cat} style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px 8px" }}>
            <Label>{cat}</Label>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...thStyle, width: 50 }}>ID</th>
                <th style={thStyle}>Descricao</th>
                <th style={{ ...thStyle, width: 120 }}>Valor</th>
                <th style={{ ...thStyle, width: 60 }}>Estado</th>
              </tr>
            </thead>
            <tbody>
              {rules.filter((r) => r.categoria === cat).map((r) => (
                <tr key={r.id}>
                  <td style={{ ...tdStyle, fontFamily: T.mono, color: T.tertiary }}>{r.id}</td>
                  <td style={{ ...tdStyle, fontFamily: "inherit" }}>{r.descricao}</td>
                  <td style={{ ...tdStyle, fontFamily: T.mono, fontWeight: 600 }}>{r.valor}</td>
                  <td style={tdStyle}><Dot color={r.activo ? T.green : T.tertiary} size={6} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ))}
    </div>
  );
}
