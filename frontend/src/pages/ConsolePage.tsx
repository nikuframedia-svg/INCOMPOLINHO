import React, { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { getConsole, getToday } from "../api/endpoints";
import { useDataStore } from "../stores/useDataStore";
import type { ConsoleData } from "../api/types";
import { Card } from "../components/ui/Card";
import { Num } from "../components/ui/Num";
import { Label } from "../components/ui/Label";
import { Dot } from "../components/ui/Dot";
import { Divider } from "../components/ui/Divider";
import { ProgressBar } from "../components/ui/ProgressBar";
import { TH } from "../constants/thresholds";

export function ConsolePage() {
  const [day, setDay] = useState<number | null>(null);
  const [data, setData] = useState<ConsoleData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const score = useDataStore((s) => s.score);

  // Auto-detect today on mount
  useEffect(() => {
    getToday().then((t) => setDay(t.today_idx)).catch(() => setDay(0));
  }, []);

  // Fetch console data when day changes
  useEffect(() => {
    if (day === null) return;
    getConsole(day)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [day]);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (day === null || !data) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const stateColor = data.state.color === "red" ? T.red : data.state.color === "yellow" ? T.orange : T.green;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* State Banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "16px 20px",
          background: T.card,
          borderRadius: T.radius,
          border: `0.5px solid ${T.border}`,
        }}
      >
        <Dot color={stateColor} size={8} />
        <span style={{ fontSize: 15, fontWeight: 500, color: T.primary, flex: 1 }}>{data.state.phrase}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: T.elevated, borderRadius: 8, padding: "4px 4px" }}>
          <button onClick={() => setDay(Math.max(-(Number(score?.buffer_days) || 0), (day ?? 0) - 1))} style={navBtnStyle}>‹</button>
          <span style={{ fontSize: 12, fontWeight: 600, color: T.primary, minWidth: 54, textAlign: "center", fontFamily: T.mono }}>
            Dia {day ?? 0}
          </span>
          <button onClick={() => setDay((day ?? 0) + 1)} style={navBtnStyle}>›</button>
        </div>
      </div>

      {/* KPI Strip */}
      {score && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12 }}>
          {[
            { l: "OTD", v: score.otd?.toFixed(1), u: "%", c: (score.otd ?? 0) >= TH.OTD_GREEN ? T.green : T.orange },
            { l: "OTD-D", v: score.otd_d?.toFixed(1), u: "%", c: (score.otd_d ?? 0) >= TH.OTD_D_GREEN ? T.green : T.orange },
            { l: "Atrasos", v: score.tardy_count, c: score.tardy_count === 0 ? T.green : T.red },
            { l: "Setups", v: score.setups, c: T.primary },
            { l: "Antecipação", v: score.earliness_avg_days?.toFixed(1), u: "d", c: T.primary },
            { l: "Buffer", v: Number(score.buffer_days) || 0, u: "d", c: T.primary },
          ].map((k, i) => (
            <Card key={i} style={{ padding: 16 }}>
              <Label>{k.l}</Label>
              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                <Num size={28} color={k.c}>{k.v}</Num>
                {k.u && <span style={{ fontSize: 13, color: T.tertiary, fontWeight: 500 }}>{k.u}</span>}
              </div>
            </Card>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Actions */}
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px 12px" }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Resumo do Dia</span>
          </div>
          {/* Day summary */}
          {data.summary?.length > 0 && (
            <div style={{ padding: "0 20px 12px" }}>
              {data.summary.map((line, i) => {
                const color = line.color === "red" ? T.red : line.color === "orange" ? T.orange : line.color === "green" ? T.green : T.secondary;
                return (
                  <div key={i} style={{ fontSize: 12, lineHeight: 1.7, color, fontFamily: line.text.startsWith("  ") ? T.mono : "inherit" }}>
                    {line.text}
                  </div>
                );
              })}
            </div>
          )}
          {/* Actions */}
          {data.actions.length > 0 && (
            <>
              <Divider />
              <div style={{ padding: "12px 20px 4px" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>Acções</span>
              </div>
            </>
          )}
          {data.actions.map((a, i) => {
            const c = a.severity === "critical" ? T.red : a.severity === "warning" ? T.orange : T.blue;
            return (
              <div key={i}>
                {i > 0 && <Divider />}
                <div style={{ padding: "10px 20px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <Dot color={c} />
                    <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>{a.title}</span>
                  </div>
                  <p style={{ fontSize: 12, color: T.secondary, lineHeight: 1.55, margin: "4px 0 10px 14px" }}>{a.detail}</p>
                  {a.suggestion && (
                    <div style={{ marginLeft: 14 }}>
                      <button style={fixBtnStyle}>{a.suggestion}</button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {data.actions.length === 0 && !data.summary?.length && (
            <div style={{ padding: "14px 20px", color: T.tertiary, fontSize: 13 }}>Sem dados para este dia</div>
          )}
        </Card>

        {/* Right column */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Machines */}
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px" }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Máquinas</span>
            </div>
            {(Array.isArray(data.machines) ? data.machines : (data.machines as any)?.machines ?? []).map((m: any, i: number) => {
              const raw = m.utilization_pct ?? (typeof m.util === "number" ? m.util * 100 : 0);
              const u = raw > 1 && raw <= 100 ? raw : raw <= 1 ? raw * 100 : raw;
              const c = u > 95 ? T.red : u > 85 ? T.orange : u > 70 ? T.blue : T.green;
              return (
                <div key={i}>
                  {i > 0 && <Divider />}
                  <div style={{ padding: "12px 20px" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: T.mono }}>{m.machine_id ?? m.id}</span>
                        {(m.current_tool ?? m.tools?.[0]?.id) && <span style={{ fontSize: 11, color: T.tertiary }}>{m.current_tool ?? m.tools?.[0]?.id}</span>}
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 600, color: c, fontFamily: T.mono }}>{(typeof u === "number" ? u : 0).toFixed(0)}%</span>
                    </div>
                    <ProgressBar value={typeof u === "number" ? u : 0} color={c} />
                    <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 11, color: T.tertiary }}>{m.runs?.length ?? m.tools?.length ?? 0} runs</span>
                      <span style={{ fontSize: 11, color: T.secondary, fontFamily: T.mono }}>{m.total_pcs ?? 0} pcs</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </Card>

          {/* Expedition */}
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px" }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Expedição</span>
            </div>
            {(Array.isArray(data.expedition) ? data.expedition : (data.expedition as any)?.clients ?? []).map((e: any, i: number) => (
              <div key={i}>
                {i > 0 && <Divider />}
                <div style={{ padding: "10px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: T.primary, flex: 1 }}>{e.client}</span>
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.green} size={5} />
                      <span style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}>{e.ready}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.orange} size={5} />
                      <span style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}>{e.partial}</span>
                    </div>
                    {e.not_ready > 0 && (
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <Dot color={T.red} size={5} />
                        <span style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}>{e.not_ready}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </Card>
        </div>
      </div>

      {/* Tomorrow Prep */}
      {data.tomorrow && (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Preparacao Amanha</span>
            {data.tomorrow.date && (
              <span style={{ fontSize: 11, color: T.tertiary, fontFamily: T.mono }}>{data.tomorrow.date}</span>
            )}
          </div>

          {(data.tomorrow.problems ?? []).length > 0 && (
            <div style={{ padding: "0 20px 12px" }}>
              {data.tomorrow.problems.map((p, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
                  <Dot color={T.orange} size={5} />
                  <span style={{ fontSize: 12, color: T.orange }}>{p}</span>
                </div>
              ))}
            </div>
          )}

          {(data.tomorrow.setups ?? []).length > 0 && (
            <>
              <Divider />
              <div style={{ padding: "12px 20px" }}>
                <Label style={{ marginBottom: 8 }}>Setups</Label>
                <div style={{ display: "grid", gridTemplateColumns: "60px 90px 1fr 50px", gap: "4px 12px" }}>
                  {data.tomorrow.setups.map((s, i) => (
                    <React.Fragment key={i}>
                      <span style={{ fontSize: 11, fontFamily: T.mono, color: T.tertiary }}>{s.time}</span>
                      <span style={{ fontSize: 11, fontFamily: T.mono, color: T.primary }}>{s.machine}</span>
                      <span style={{ fontSize: 11, color: T.secondary }}>
                        {s.from_tool ? `${s.from_tool} → ` : ""}{s.to_tool}
                        {s.already_mounted && <span style={{ color: T.green, marginLeft: 4 }}>(montada)</span>}
                      </span>
                      <span style={{ fontSize: 11, fontFamily: T.mono, color: T.tertiary, textAlign: "right" }}>{s.duration_min}m</span>
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </>
          )}

          {(data.tomorrow.operators ?? []).length > 0 && (
            <>
              <Divider />
              <div style={{ padding: "12px 20px" }}>
                <Label style={{ marginBottom: 8 }}>Operadores</Label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "4px 12px" }}>
                  <span style={{ fontSize: 10, color: T.tertiary, textTransform: "uppercase" }}>Turno</span>
                  <span style={{ fontSize: 10, color: T.tertiary, textTransform: "uppercase" }}>Grupo</span>
                  <span style={{ fontSize: 10, color: T.tertiary, textTransform: "uppercase" }}>Necessarios</span>
                  <span style={{ fontSize: 10, color: T.tertiary, textTransform: "uppercase" }}>Deficit</span>
                  {data.tomorrow.operators.map((o, i) => (
                    <React.Fragment key={i}>
                      <span style={{ fontSize: 12, fontFamily: T.mono, color: T.primary }}>{o.shift}</span>
                      <span style={{ fontSize: 12, color: T.secondary }}>{o.group}</span>
                      <span style={{ fontSize: 12, fontFamily: T.mono, color: T.primary }}>{o.required}</span>
                      <span style={{ fontSize: 12, fontFamily: T.mono, color: o.deficit > 0 ? T.red : T.green, fontWeight: o.deficit > 0 ? 600 : 400 }}>
                        {o.deficit > 0 ? `-${o.deficit}` : "OK"}
                      </span>
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </>
          )}

          {data.tomorrow.expeditions_summary && (
            <>
              <Divider />
              <div style={{ padding: "12px 20px" }}>
                <Label style={{ marginBottom: 4 }}>Expedicoes</Label>
                <span style={{ fontSize: 12, color: T.secondary }}>{data.tomorrow.expeditions_summary}</span>
              </div>
            </>
          )}

          {data.tomorrow.ok && (data.tomorrow.problems ?? []).length === 0 && (
            <div style={{ padding: "12px 20px" }}>
              <span style={{ fontSize: 12, color: T.green }}>Tudo preparado para amanha.</span>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: T.secondary,
  cursor: "pointer",
  padding: "4px 8px",
  borderRadius: 6,
  fontSize: 13,
  fontFamily: "inherit",
};

const fixBtnStyle: React.CSSProperties = {
  background: T.elevated,
  border: `0.5px solid ${T.border}`,
  color: T.blue,
  fontSize: 11,
  fontWeight: 500,
  padding: "5px 10px",
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: "inherit",
};
