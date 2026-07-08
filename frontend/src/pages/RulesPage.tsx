import { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { getConfig } from "../api/endpoints";
import type { FactoryConfig } from "../api/types";
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
    { id: "F03", categoria: "Leis físicas", descricao: "Uma única equipa de setup não faz dois setups simultâneos", valor: `setup_crews = ${config.setup_crews}`, activo: config.setup_crews === 1 },
    { id: "F04", categoria: "Leis físicas", descricao: "Máquina ou ferramenta bloqueada não produz", valor: "blocked = 0", activo: true },
    { id: "F05", categoria: "Leis físicas", descricao: "Capacidade diária por máquina não é excedida", valor: `${config.day_capacity_min} min`, activo: true },
    { id: "E01", categoria: "Entregas", descricao: "Cumprimento total por lote", valor: "OTD = 100%", activo: true },
    { id: "E02", categoria: "Entregas", descricao: "Cumprimento acumulado por dia", valor: "OTD-D = 100%", activo: true },
    { id: "E03", categoria: "Entregas", descricao: "Nenhum lote atrasado", valor: "Atrasos = 0", activo: true },
    { id: "B01", categoria: "Negócio", descricao: "Eco lot hard", valor: String(config.eco_lot_mode), activo: true },
    { id: "B02", categoria: "Negócio", descricao: "Gémeas produzem em simultâneo", valor: `${config.twins.length} regras`, activo: true },
    { id: "B03", categoria: "Negócio", descricao: "PRM020 ignorada se inativa", valor: config.machines.PRM020?.active === false ? "Inativa" : "Verificar", activo: config.machines.PRM020?.active === false },
    { id: "P01", categoria: "Preferências", descricao: "Produzir o mais tarde possível sem falhar entregas", valor: config.jit_enabled ? "Activo" : "Inactivo", activo: config.jit_enabled },
    { id: "P02", categoria: "Preferências", descricao: "Reduzir setups em campanhas válidas", valor: `${config.campaign_window} dias`, activo: true },
    { id: "P03", categoria: "Preferências", descricao: "Evitar antecipação excessiva", valor: `${config.jit_earliness_target ?? 5.5} dias`, activo: true },
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
  const [config, setConfig] = useState<FactoryConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!config) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const rules = buildRules(config);
  const categorias = [...new Set(rules.map((r) => r.categoria))];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, color: T.secondary }}>
        {rules.length} regras activas do scheduler. Editaveis em Configuracao → Parametros.
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
