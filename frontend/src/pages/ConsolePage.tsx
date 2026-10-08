import React, { useCallback, useEffect, useState } from "react";
import { usePlanQuery } from "../hooks/usePlanQuery";
import { T } from "../theme/tokens";
import { getConsole, getToday, getWorkdays } from "../api/endpoints";
import { useDataStore } from "../stores/useDataStore";
import type { ConsoleData, ConsoleMachine, ConsoleExpedition } from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Dot } from "../components/ui/Dot";
import { Divider } from "../components/ui/Divider";
import { ProgressBar } from "../components/ui/ProgressBar";
import { useAppStore } from "../stores/useAppStore";
import {
  lateOrderRows,
  longProductionRows,
  plural,
  riskCauseLabel,
  riskStatus,
  riskStatusLabel,
  type LongProductionRow,
  type RiskStatus,
} from "../lib/consoleRisks";

function formatClock(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number" || /^\d+(\.\d+)?$/.test(String(value))) {
    const total = Math.round(Number(value));
    if (!Number.isFinite(total)) return String(value);
    const minutes = ((total % 1440) + 1440) % 1440;
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  }
  const parsed = new Date(String(value));
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
  }
  return String(value);
}

type SetupItem = NonNullable<ConsoleData["tomorrow"]>["setups"][number];
type ConsoleDayOverview = {
  today?: {
    unavailable_count?: number;
    trial_count?: number;
    expedition?: { ready: number; partial: number; not_ready: number };
  };
  tomorrow?: {
    setups_count?: number;
    operator_deficit?: number;
    problems_count?: number;
    expeditions_summary?: string;
  };
};

const LAST_CONSOLE_DAY_KEY = "pp1ConsoleLastDay";

function readStoredDay() {
  try {
    const raw = window.localStorage.getItem(LAST_CONSOLE_DAY_KEY);
    if (raw === null) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
  } catch {
    return null;
  }
}

function rememberDay(day: number) {
  try {
    window.localStorage.setItem(LAST_CONSOLE_DAY_KEY, String(day));
  } catch {
    // Best effort only. Navigation must keep working if storage is unavailable.
  }
}

function riskStatusColor(status: RiskStatus | null) {
  return status === "late" ? T.red : status === "at_limit" ? T.orange : T.yellow;
}

function riskConsequence(status: RiskStatus | null, slackDays: unknown) {
  const slack = Number(slackDays);
  if (status === "late") {
    return Number.isFinite(slack) && slack < 0
      ? `acaba ${plural(Math.abs(slack), "dia", "dias")} depois do prazo de produção`
      : "acaba depois do prazo de produção";
  }
  if (status === "at_limit") return "acaba no último dia do prazo de produção";
  if (Number.isFinite(slack)) return `${plural(slack, "dia", "dias")} de folga`;
  return null;
}

function formatQty(value: number) {
  return Math.round(value).toLocaleString("pt-PT");
}

const LATE_ORDERS_SHOWN = 10;

function consecutiveDays(count: number | null) {
  return count === null ? "— dias seguidos" : plural(count, "dia seguido", "dias seguidos");
}

function longProductionText(item: LongProductionRow) {
  let text = `${consecutiveDays(item.workdays)} · limite: ${consecutiveDays(item.limit_workdays)}`;
  if (item.total_days !== null && item.consecutive_days !== null && item.total_days > item.consecutive_days) {
    const extra = item.total_days - item.consecutive_days;
    text += ` · volta à máquina mais ${plural(extra, "dia", "dias")} depois de uma pausa`;
  }
  return text;
}

function groupLabel(group: string) {
  return group === "Medias" ? "Médias" : group;
}

function getDayOverview(data: ConsoleData) {
  return (data as ConsoleData & { day_overview?: ConsoleDayOverview }).day_overview;
}

function setupKey(setup: SetupItem, index: number) {
  return `${setup.machine}-${setup.start_min ?? setup.time}-${setup.to_tool}-${index}`;
}

function SetupSection({
  title,
  date,
  setups,
  emptyText,
}: {
  title: string;
  date?: string | null;
  setups: SetupItem[];
  emptyText: string;
}) {
  const byShift = setups.reduce<Record<string, SetupItem[]>>((acc, setup) => {
    const shift = String(setup.shift || "Sem turno");
    (acc[shift] ??= []).push(setup);
    return acc;
  }, {});
  const shifts = Object.keys(byShift).sort((a, b) => a.localeCompare(b, "pt-PT", { numeric: true }));
  return (
    <div style={{ borderTop: `1px solid ${T.border}`, padding: "12px 20px" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
        <Label>{title}</Label>
        {date && <span style={{ color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>{date}</span>}
      </div>
      {setups.length === 0 ? (
        <div style={{ color: T.tertiary, fontSize: 12 }}>{emptyText}</div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {shifts.map((shift) => (
            <div key={shift}>
              <div style={{ color: T.primary, fontSize: 11, fontWeight: 650, marginBottom: 5 }}>
                Turno {shift}
              </div>
              <div style={{ display: "grid", gap: 7 }}>
                {byShift[shift].map((setup, index) => (
                  <div key={setupKey(setup, index)} style={{ display: "grid", gridTemplateColumns: "52px 70px minmax(0, 1fr) 48px", gap: 8, alignItems: "center", fontSize: 11 }}>
                    <span style={{ color: T.tertiary, fontFamily: T.mono }}>{setup.time}</span>
                    <span style={{ color: T.primary, fontFamily: T.mono }}>{setup.machine}</span>
                    <span style={{ color: T.secondary, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {setup.from_tool ? `${setup.from_tool} → ` : ""}{setup.to_tool}
                      {setup.already_mounted && <span style={{ color: T.green, marginLeft: 4 }}>(montada)</span>}
                    </span>
                    <span style={{ color: T.tertiary, fontFamily: T.mono, textAlign: "right" }}>{setup.duration_min}m</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div style={{ color: T.primary, fontSize: 12, fontWeight: 700, marginBottom: 5 }}>{title}</div>
      <ul style={{ margin: "0 0 0 18px", padding: 0, display: "grid", gap: 3 }}>
        {items.length === 0 ? (
          <li style={summaryBulletStyle}>Sem ocorrências.</li>
        ) : items.map((item, index) => (
          <li key={`${title}-${index}`} style={summaryBulletStyle}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

type AvailabilityLine = { label: string; value: string; active: boolean };

function UnavailableSummary({ lines }: { lines: AvailabilityLine[] }) {
  const hasUnavailable = lines.some((line) => line.active);
  return (
    <section
      aria-label="Recursos indisponíveis"
      style={{
        margin: "-8px -12px",
        padding: "8px 12px",
        borderLeft: `3px solid ${hasUnavailable ? T.red : "transparent"}`,
        background: hasUnavailable ? "#FFF3EE" : "transparent",
      }}
    >
      <div style={{ color: hasUnavailable ? T.red : T.primary, fontSize: 12, fontWeight: 700, marginBottom: 5 }}>
        RECURSOS INDISPONÍVEIS:
      </div>
      <ul style={{ margin: "0 0 0 18px", padding: 0, display: "grid", gap: 3 }}>
        {lines.map((line) => (
          <li
            key={line.label}
            style={{
              ...summaryBulletStyle,
              color: line.active ? T.red : T.secondary,
              fontWeight: line.active ? 700 : 400,
              overflowWrap: "anywhere",
            }}
          >
            {line.label}: {line.value}
          </li>
        ))}
      </ul>
    </section>
  );
}

const loadConsoleCalendar = () => Promise.all([getToday(), getWorkdays()]);

export function ConsolePage() {
  const [selectedDay, setDay] = useState<number | null>(readStoredDay);
  const { data: calendar, error: calendarError } = usePlanQuery("calendar", loadConsoleCalendar);
  const todayDay = calendar?.[0].today_idx ?? 0;
  const workdays = calendar?.[1] ?? [];
  const day = calendar ? Math.min(selectedDay ?? todayDay, Math.max(0, workdays.length - 1)) : null;
  const loadConsole = useCallback(() => day === null ? Promise.resolve(null) : getConsole(day), [day]);
  const { data, error: queryError } = usePlanQuery(JSON.stringify(day), loadConsole);
  const error = calendarError ?? queryError;
  const [datePickerError, setDatePickerError] = useState<string | null>(null);
  const score = useDataStore((s) => s.score);
  const gateReport = useDataStore((s) => s.gateReport);
  const setPage = useAppStore((s) => s.setPage);

  useEffect(() => {
    if (day !== null) rememberDay(day);
  }, [day]);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (day === null || !data) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const stateColor = data.state.color === "red" ? T.red : data.state.color === "yellow" ? T.orange : T.green;
  // Keep the operational console usable during rolling deployments where an
  // older backend may not expose the newest optional panels yet.
  const setupsToday = Array.isArray(data.setups_today) ? data.setups_today : [];
  // The server already keeps only real risks in the 7-day window, most serious first.
  const topRisks = Array.isArray(data.top_risks) ? data.top_risks : [];
  const hasLateOrderInfo = Array.isArray(gateReport?.late_order_detail);
  const lateOrders = lateOrderRows(gateReport);
  const ordersLateTotal = Number(gateReport?.metrics?.orders_late);
  const lateOrdersCount = Number.isFinite(ordersLateTotal) ? Math.max(ordersLateTotal, lateOrders.length) : lateOrders.length;
  const longProductions = longProductionRows(gateReport);
  const lateOrdersShown = Math.min(lateOrders.length, LATE_ORDERS_SHOWN);
  // The report lists at most 50 orders; the remainder comes from the full count.
  const lateOrdersHidden = Math.max(lateOrdersCount - lateOrdersShown, 0);
  const operational = data.operational_summary;
  const dayOverview = getDayOverview(data);
  const machinesList = Array.isArray(data.machines)
    ? data.machines
    : (data.machines as { machines?: ConsoleMachine[] })?.machines ?? [];
  const expeditionList = Array.isArray(data.expedition)
    ? data.expedition
    : (data.expedition as { clients?: ConsoleExpedition[] })?.clients ?? [];
  const tomorrow = data.tomorrow;
  const tomorrowSetups = Array.isArray(tomorrow?.setups) ? tomorrow.setups : [];
  const tomorrowProblems = Array.isArray(tomorrow?.problems) ? tomorrow.problems : [];
  const tomorrowOperators = Array.isArray(tomorrow?.operators) ? tomorrow.operators : [];
  const tomorrowDeficits = tomorrowOperators.filter((item) => item.deficit > 0);
  const unavailableLines: AvailabilityLine[] = operational ? [
    {
      label: "Máquinas",
      value: operational.unavailable.machines.map((item) => item.resource).join(", ") || "nenhuma",
      active: operational.unavailable.machines.length > 0,
    },
    {
      label: "Ferramentas",
      value: operational.unavailable.tools.map((item) => item.resource).join(", ") || "nenhuma",
      active: operational.unavailable.tools.length > 0,
    },
    {
      label: "Pessoas",
      value: operational.unavailable.operators.map((item) => `${groupLabel(item.group)} ${item.shift}: ${item.count}`).join("; ") || "nenhuma",
      active: operational.unavailable.operators.length > 0,
    },
  ] : [];
  const unavailableCount = operational
    ? operational.unavailable.machines.length + operational.unavailable.tools.length + operational.unavailable.operators.length
    : 0;
  const dayTitle = day === todayDay ? "Hoje" : day < 0 ? "Preparação" : `Dia ${day}`;
  const dayMeta = day < 0 ? `${Math.abs(day)} dia${Math.abs(day) === 1 ? "" : "s"} antes do horizonte` : data.date ?? `Dia ${day}`;
  const pickerDate = day >= 0 ? workdays[day] ?? data.date ?? "" : "";
  const firstPickerDate = workdays[0] ?? undefined;
  const lastPickerDate = workdays.length ? workdays[workdays.length - 1] : undefined;
  const setConsoleDay = (next: number) => {
    setDay(next);
    setDatePickerError(null);
  };
  const selectCalendarDate = (value: string) => {
    if (!value) return;
    const idx = workdays.indexOf(value);
    if (idx < 0) {
      setDatePickerError("Data fora do horizonte do plano.");
      return;
    }
    setConsoleDay(idx);
  };
  const statePhrase = data.state.phrase.replace(/\s*Sem problemas\.?/gi, "").trim() || "Operação do dia atualizada.";
  const productionBullets = operational?.production_by_group.map((item) => (
    `${groupLabel(item.group)}: ${item.count} máquina${item.count === 1 ? "" : "s"} a produzir`
  )) ?? [];
  const setupBullets = operational?.production_by_group.map((item) => {
    const count = operational.setups_by_group_shift
      .filter((setup) => setup.group === item.group)
      .reduce((total, setup) => total + setup.count, 0);
    return `${groupLabel(item.group)}: ${count}`;
  }) ?? [];
  const riskBullets = topRisks.map((risk) => {
    const machine = String(risk.planned_machine_id || risk.machine_id || "");
    const parts = [machine, risk.sku, riskStatusLabel(risk), riskCauseLabel(risk)].filter(Boolean);
    return parts.join(" · ");
  });
  const trialBullets = operational?.trials.map((trial) => (
    `${trial.machine_id}${trial.tool_id ? ` · ${trial.tool_id}` : ""}`
  )) ?? [];
  const machineAverageUtilization = machinesList.length
    ? machinesList.reduce((total, machine) => {
        const raw = machine.utilization_pct ?? 0;
        const normalized = raw > 1 && raw <= 100 ? raw : raw <= 1 ? raw * 100 : raw;
        return total + normalized;
      }, 0) / machinesList.length
    : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minHeight: "100%" }}>
      <div
        className="console-day-bar"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          padding: "12px 24px",
          background: T.bg,
          borderBottom: `1px solid ${T.border}`,
          boxShadow: `0 1px 0 ${T.border}`,
        }}
      >
        <div
          className="console-day-bar-row"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
              <Dot color={stateColor} size={8} />
              <span style={{ color: T.primary, fontSize: 18, fontWeight: 700 }}>{dayTitle}</span>
              <span style={{ color: T.tertiary, fontSize: 12, fontFamily: T.mono, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {dayMeta}
              </span>
            </div>
            <div style={{ color: T.secondary, fontSize: 12, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {statePhrase}
            </div>
          </div>
          <div
            className="console-date-navigation"
            style={{ display: "grid", gap: 4, justifyItems: "end", flexShrink: 0 }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, background: T.elevated, borderRadius: 8, padding: "4px 4px" }}>
              <button onClick={() => setConsoleDay(Math.max(-(Number(score?.buffer_days) || 0), (day ?? 0) - 1))} style={navBtnStyle}>‹</button>
              {day < 0 ? (
                <span style={{ fontSize: 12, fontWeight: 600, color: T.primary, minWidth: 108, textAlign: "center", fontFamily: T.mono }}>
                  D{day}
                </span>
              ) : (
                <input
                  aria-label="Escolher data"
                  type="date"
                  value={pickerDate}
                  min={firstPickerDate}
                  max={lastPickerDate}
                  onChange={(event) => selectCalendarDate(event.target.value)}
                  style={dateInputStyle}
                />
              )}
              <button onClick={() => setConsoleDay((day ?? 0) + 1)} style={navBtnStyle}>›</button>
              <button
                onClick={() => setConsoleDay(todayDay)}
                disabled={day === todayDay}
                style={{
                  ...navBtnStyle,
                  borderLeft: `1px solid ${T.border}`,
                  color: day === todayDay ? T.tertiary : T.blue,
                  cursor: day === todayDay ? "default" : "pointer",
                  fontSize: 11,
                }}
              >
                Hoje
              </button>
            </div>
            {datePickerError && (
              <span style={{ color: T.orange, fontSize: 10 }}>{datePickerError}</span>
            )}
          </div>
        </div>
      </div>

      <div
        className="console-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
          gap: 16,
          padding: "0 24px 24px",
          alignItems: "start",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Card style={{ padding: 0, overflow: "hidden" }}>
          <div
            className="console-summary-header"
            style={{
              padding: "16px 20px 12px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Resumo do Dia</span>
            {(dayOverview || operational) && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <span style={{
                  ...summaryChipStyle,
                  ...(unavailableCount > 0 ? {
                    color: T.red,
                    background: "#FFF3EE",
                    borderColor: T.red,
                    fontWeight: 700,
                  } : {}),
                }}>Indisp. {Math.max(dayOverview?.today?.unavailable_count ?? 0, unavailableCount)}</span>
                <span style={summaryChipStyle}>Ensaios {dayOverview?.today?.trial_count ?? operational?.trials.length ?? 0}</span>
                <span style={summaryChipStyle}>Amanhã {dayOverview?.tomorrow?.setups_count ?? tomorrowSetups.length} setups</span>
              </div>
            )}
          </div>

          {operational && (
            <div style={{ padding: "0 20px 16px", display: "grid", gap: 14 }}>
              <SummaryBlock title="PRODUÇÃO:" items={productionBullets} />
              <SummaryBlock title="SETUPS:" items={setupBullets} />
              <SummaryBlock title="RISCOS:" items={riskBullets} />
              <UnavailableSummary lines={unavailableLines} />
              <SummaryBlock title="ENSAIOS:" items={trialBullets} />
              <div style={{ color: T.secondary, fontSize: 11, fontFamily: T.mono }}>
                Ocupação média: {operational.average_utilization_pct.toFixed(0)}% · Expedições: {operational.expedition.ready} prontas · {operational.expedition.partial} parciais · {operational.expedition.not_ready} em falta
              </div>
            </div>
          )}

          {(tomorrowProblems.length > 0 || tomorrowDeficits.length > 0) && (
            <>
              <Divider />
              <div style={{ padding: "12px 20px" }}>
                <Label style={{ marginBottom: 8 }}>Amanhã</Label>
                <div style={{ display: "grid", gap: 6 }}>
                  {tomorrowProblems.map((problem, index) => (
                    <div key={`${problem}-${index}`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Dot color={T.orange} size={5} />
                      <span style={{ fontSize: 12, color: T.orange }}>{problem}</span>
                    </div>
                  ))}
                  {tomorrowDeficits.map((operator, index) => (
                    <div key={`${operator.group}-${operator.shift}-${index}`} style={{ display: "grid", gridTemplateColumns: "48px minmax(0, 1fr) 76px 56px", gap: 8, fontSize: 11 }}>
                      <span style={{ color: T.primary, fontFamily: T.mono }}>{operator.shift}</span>
                      <span style={{ color: T.secondary }}>{groupLabel(operator.group)}</span>
                      <span style={{ color: T.secondary, fontFamily: T.mono }}>{operator.required}/{operator.available}</span>
                      <span style={{ color: T.red, fontFamily: T.mono, fontWeight: 600 }}>-{operator.deficit}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {data.actions.length > 0 && (
            <>
              <Divider />
              <div style={{ padding: "12px 20px 4px" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>Ações</span>
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
                    <div style={{ marginLeft: 14, fontSize: 11, color: T.blue, lineHeight: 1.5 }}>
                      Sugestão: {a.suggestion}
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

          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px" }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Setups</span>
              <div style={{ color: T.tertiary, fontSize: 10, marginTop: 4 }}>
                Hoje e próxima preparação
              </div>
            </div>
            <SetupSection title="Hoje" date={data.date} setups={setupsToday} emptyText="Não há setups planeados." />
            <SetupSection title="Amanhã" date={tomorrow?.date} setups={tomorrowSetups} emptyText="Não há setups planeados para amanhã." />
          </Card>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Máquinas</span>
              <span style={{ fontSize: 12, fontWeight: 650, color: T.secondary, fontFamily: T.mono }}>
                Ocupação Média {machineAverageUtilization.toFixed(0)}%
              </span>
            </div>
            {machinesList.length === 0 ? (
              <div style={{ padding: "0 20px 16px", color: T.tertiary, fontSize: 12 }}>Não há máquinas em produção neste dia.</div>
            ) : machinesList.map((m: ConsoleMachine, i: number) => {
              const raw = m.utilization_pct ?? 0;
              const u = raw > 1 && raw <= 100 ? raw : raw <= 1 ? raw * 100 : raw;
              const c = u > 95 ? T.red : u > 85 ? T.orange : u > 70 ? T.blue : T.green;
              return (
                <div key={i}>
                  {i > 0 && <Divider />}
                  <div style={{ padding: "12px 20px" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8, gap: 12 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: T.mono }}>{m.machine_id}</span>
                        {m.current_state && m.current_state !== "idle" && (
                          <span
                            title="Estado atual da máquina"
                            style={{ fontSize: 9, color: m.current_state === "down" ? T.red : T.blue, background: T.elevated, borderRadius: 5, padding: "2px 5px" }}
                          >
                            {{ producing: "A produzir", setup: "Setup", trial: "Ensaio", down: "Avariada" }[m.current_state]}
                          </span>
                        )}
                        {m.current_tool && <span style={{ fontSize: 11, color: T.tertiary }}>{m.current_tool}</span>}
                        {m.group && <span style={{ fontSize: 10, color: T.tertiary }}>· {groupLabel(m.group)}</span>}
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 600, color: c, fontFamily: T.mono, flexShrink: 0 }}>{u.toFixed(0)}%</span>
                    </div>
                    <ProgressBar value={u} color={c} />
                    {m.current_sku && (
                      <div style={{ marginTop: 6, color: T.primary, fontSize: 10, fontFamily: T.mono }}>
                        Agora: {m.current_sku}{m.eta_current ? ` · fim previsto ${formatClock(m.eta_current)}` : ""}
                      </div>
                    )}
                    <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={{ fontSize: 11, color: T.tertiary }}>{m.runs?.length ?? 0} referências</span>
                      <span style={{ fontSize: 11, color: T.secondary, fontFamily: T.mono }}>{m.total_pcs ?? 0} pç</span>
                    </div>
                    {m.runs?.length > 0 && (
                      <div style={{ marginTop: 9, display: "grid", gap: 5 }}>
                        {m.runs.map((run, runIndex) => (
                          <div key={`${run.lot_id}-${run.start_min}-${runIndex}`} style={{ display: "grid", gridTemplateColumns: "96px minmax(120px, 1fr) 88px 86px", gap: 10, alignItems: "center", fontSize: 10 }}>
                            <span style={{ color: T.tertiary, fontFamily: T.mono }}>{run.start}–{run.end}</span>
                            <span title={run.sku} style={{ color: T.primary, fontFamily: T.mono, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.sku}</span>
                            <span title={run.tool_id} style={{ color: T.secondary, fontFamily: T.mono, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.tool_id}</span>
                            <span style={{ color: T.secondary, fontFamily: T.mono, textAlign: "right" }}>{run.qty.toLocaleString()} pç</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </Card>

          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px" }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Expedições</span>
              <div style={{ color: T.tertiary, fontSize: 10, marginTop: 4 }}>
                Por cliente: prontas · parciais · em falta
              </div>
            </div>
            {expeditionList.length === 0 ? (
              <div style={{ padding: "0 20px 14px", color: T.tertiary, fontSize: 12 }}>Não há expedições neste dia.</div>
            ) : expeditionList.map((e: ConsoleExpedition, i: number) => (
              <div key={i}>
                {i > 0 && <Divider />}
                <div style={{ padding: "10px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: T.primary, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.client}</span>
                  <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.green} size={5} />
                      <span style={{ fontSize: 11, color: T.secondary }}>Prontas <b style={{ fontFamily: T.mono }}>{e.ready}</b></span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <Dot color={T.orange} size={5} />
                      <span style={{ fontSize: 11, color: T.secondary }}>Parciais <b style={{ fontFamily: T.mono }}>{e.partial}</b></span>
                    </div>
                    {e.not_ready > 0 && (
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <Dot color={T.red} size={5} />
                        <span style={{ fontSize: 11, color: T.secondary }}>Em falta <b style={{ fontFamily: T.mono }}>{e.not_ready}</b></span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {tomorrow?.expeditions_summary && (
              <>
                <Divider />
                <div style={{ padding: "12px 20px" }}>
                  <Label style={{ marginBottom: 4 }}>Amanhã{tomorrow.date ? ` · ${tomorrow.date}` : ""}</Label>
                  <span style={{ fontSize: 12, color: T.secondary }}>{tomorrow.expeditions_summary}</span>
                </div>
              </>
            )}
          </Card>

          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px" }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Lotes em risco</span>
              <div style={{ color: T.tertiary, fontSize: 10, marginTop: 4 }}>
                Próximos 7 dias: atrasados, no limite ou com pouca folga
              </div>
            </div>
            {topRisks.length === 0 ? (
              <div style={{ padding: "0 20px 16px", color: T.green, fontSize: 12 }}>Sem lotes em risco nos próximos 7 dias.</div>
            ) : topRisks.map((risk, index) => {
              const status = riskStatus(risk);
              const statusLabel = riskStatusLabel(risk);
              const cause = riskCauseLabel(risk);
              const consequence = riskConsequence(status, risk.slack_days);
              const color = riskStatusColor(status);
              const details = [consequence, cause ? `Causa: ${cause}` : null].filter(Boolean).join(" · ");
              return (
                <div key={risk.lot_id} style={{ borderTop: index > 0 ? `1px solid ${T.border}` : undefined, padding: "10px 20px", display: "flex", gap: 12, alignItems: "center" }}>
                  <Dot color={color} size={6} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ color: T.primary, fontSize: 11, fontFamily: T.mono }}>{risk.sku}</div>
                    {(statusLabel || details) && (
                      <div style={{ color: T.tertiary, fontSize: 10, marginTop: 2 }}>
                        {statusLabel && <b style={{ color, fontWeight: 600 }}>{statusLabel}</b>}
                        {statusLabel && details ? " · " : ""}
                        {details}
                      </div>
                    )}
                    <div style={{ color: T.secondary, fontSize: 10, marginTop: 3, fontFamily: T.mono }}>
                      Produção: {risk.production_date ?? `dia ${risk.production_day ?? "?"}`} · Máquina: {risk.planned_machine_id ?? risk.machine_id ?? "?"}
                      {risk.completion_date ? ` · Conclusão: ${risk.completion_date}` : ""}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      sessionStorage.setItem("pp1PlanFocus", JSON.stringify({
                        day: Number(risk.completion_day ?? risk.edd),
                        query: risk.lot_id || risk.sku,
                      }));
                      setPage("gantt");
                    }}
                    style={{ ...navBtnStyle, color, fontSize: 10, fontWeight: 600, border: `1px solid ${color}55` }}
                  >
                    Abrir no plano
                  </button>
                </div>
              );
            })}
          </Card>

          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "16px 20px 12px", display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
              <div>
                <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Encomendas atrasadas</span>
                <div style={{ color: T.tertiary, fontSize: 10, marginTop: 4 }}>
                  Encomendas que não ficam prontas até ao dia de entrega
                </div>
              </div>
              <span style={{ ...summaryChipStyle, ...(lateOrdersCount > 0 ? { color: T.red, borderColor: T.red } : {}) }}>
                {hasLateOrderInfo ? lateOrdersCount : "—"}
              </span>
            </div>
            {!hasLateOrderInfo ? (
              <div style={{ padding: "0 20px 16px", color: T.tertiary, fontSize: 12 }}>—</div>
            ) : lateOrdersCount === 0 ? (
              <div style={{ padding: "0 20px 16px", color: T.green, fontSize: 12 }}>Todas as encomendas ficam prontas a tempo.</div>
            ) : (
              <>
                {lateOrders.slice(0, LATE_ORDERS_SHOWN).map((order, index) => (
                  <div
                    key={`${order.client}-${order.sku}-${order.due_day}-${index}`}
                    data-testid="late-order-row"
                    style={{ borderTop: index > 0 ? `1px solid ${T.border}` : undefined, padding: "10px 20px", display: "flex", gap: 12, alignItems: "center" }}
                  >
                    <Dot color={T.red} size={6} />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "baseline", minWidth: 0 }}>
                        <span style={{ color: T.primary, fontSize: 12, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{order.client || "Cliente desconhecido"}</span>
                        <span style={{ color: T.secondary, fontSize: 11, fontFamily: T.mono }}>{order.sku}</span>
                        {order.machine_id && <span style={{ color: T.secondary, fontSize: 11 }}>{order.machine_id}</span>}
                      </div>
                      <div style={{ color: T.tertiary, fontSize: 10, marginTop: 2 }}>
                        {`No dia de entrega faltam ${formatQty(order.shortfall_qty)} de ${formatQty(order.order_qty)} pç`}
                        {order.due_day !== null ? ` · Entrega: dia ${order.due_day}` : ""}
                        {order.ready_day !== null ? ` · Pronta: dia ${order.ready_day}` : ""}
                      </div>
                    </div>
                    <span style={{ color: T.red, fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>
                      {order.late_days === null ? "não fica completa no plano" : `${plural(order.late_days, "dia", "dias")} de atraso`}
                    </span>
                  </div>
                ))}
                {lateOrdersHidden > 0 && (
                  <div style={{ padding: "8px 20px 14px", color: T.tertiary, fontSize: 11, borderTop: `1px solid ${T.border}` }}>
                    e mais {plural(lateOrdersHidden, "encomenda atrasada", "encomendas atrasadas")}
                  </div>
                )}
              </>
            )}
          </Card>

          {longProductions.length > 0 && (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "16px 20px 12px" }}>
                <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Produções longas</span>
                <div style={{ color: T.tertiary, fontSize: 10, marginTop: 4 }}>
                  A mesma referência fica na máquina mais dias seguidos do que o limite definido nos Parâmetros
                </div>
              </div>
              {longProductions.map((item, index) => (
                <div
                  key={`${item.lot_id}-${index}`}
                  data-testid="long-production-row"
                  style={{ borderTop: index > 0 ? `1px solid ${T.border}` : undefined, padding: "10px 20px", display: "flex", gap: 12, alignItems: "center" }}
                >
                  <Dot color={T.orange} size={6} />
                  <div style={{ minWidth: 0, flex: 1, display: "flex", gap: 8, alignItems: "baseline" }}>
                    <span style={{ color: T.primary, fontSize: 12, fontWeight: 500 }}>{item.machine_id || "?"}</span>
                    <span style={{ color: T.secondary, fontSize: 11, fontFamily: T.mono }}>{item.sku}</span>
                  </div>
                  <span style={{ color: T.secondary, fontSize: 11, textAlign: "right" }}>
                    {longProductionText(item)}
                  </span>
                </div>
              ))}
            </Card>
          )}
        </div>
      </div>
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

const dateInputStyle: React.CSSProperties = {
  background: "transparent",
  border: "none",
  color: T.primary,
  fontSize: 12,
  fontWeight: 650,
  fontFamily: T.mono,
  minWidth: 124,
  textAlign: "center",
  outline: "none",
  padding: "3px 2px",
};

const summaryChipStyle: React.CSSProperties = {
  color: T.secondary,
  background: T.elevated,
  border: `1px solid ${T.border}`,
  borderRadius: 6,
  padding: "3px 6px",
  fontSize: 10,
  fontFamily: T.mono,
};

const summaryBulletStyle: React.CSSProperties = {
  color: T.secondary,
  fontSize: 12,
  lineHeight: 1.45,
};
