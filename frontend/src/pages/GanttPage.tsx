import { useEffect, useMemo, useState } from "react";
import { T, toolColor } from "../theme/tokens";
import { useDataStore } from "../stores/useDataStore";
import { getWorkdays } from "../api/endpoints";
import type { Segment, Score } from "../api/types";
import { Card } from "../components/ui/Card";
import { ProgressBar } from "../components/ui/ProgressBar";
import { Modal } from "../components/ui/Modal";
import { Pill } from "../components/ui/Pill";
import { Dot } from "../components/ui/Dot";

const DEFAULT_DAY_W = 110;
const LANE_H = 60;
const SHIFT_CHANGE = 930;
const DAY_START = 420;
const DAY_CAP = 1020;
const FALLBACK_MACHINES = ["PRM019", "PRM031", "PRM039", "PRM042", "PRM043"];
const SINGLE_BAR_H = 52;
const SINGLE_BAR_PAD = 8;

// ── Helpers ──────────────────────────────────────────────────

const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const DOWS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"];

function fmtDate(iso: string): { short: string; dow: string } {
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

function fmtMin(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h % 24).padStart(2, "0")}:${String(Math.round(m)).padStart(2, "0")}`;
}

function buildDayLogic(segs: Segment[], dayIdx: number): string {
  const parts: string[] = [];
  const sorted = [...segs].sort((a, b) => a.start_min - b.start_min);

  const setupSegs = sorted.filter((s) => s.setup_min > 0);
  if (setupSegs.length > 0) {
    parts.push(`Setup: ${setupSegs.map((s) => `${s.tool_id} (${s.setup_min.toFixed(0)}min)`).join(", ")}`);
  }

  const byTool: Record<string, { qty: number; skus: Set<string> }> = {};
  for (const s of sorted) {
    const e = (byTool[s.tool_id] ??= { qty: 0, skus: new Set() });
    e.qty += s.qty;
    e.skus.add(s.sku);
  }
  for (const [tool, info] of Object.entries(byTool)) {
    parts.push(`${tool}: ${info.qty} pç (${[...info.skus].join("+")})`);
  }

  const dayEdds = sorted.filter((s) => s.edd === dayIdx);
  if (dayEdds.length > 0) parts.push(`${dayEdds.length} deadline(s) hoje`);

  const twins = sorted.filter((s) => s.twin_outputs);
  if (twins.length > 0) parts.push(`${twins.length} seg. gémeos`);

  const conts = sorted.filter((s) => s.is_continuation);
  if (conts.length > 0) parts.push(`${conts.length} continuação(ões)`);

  return parts.join(". ") + ".";
}

function exportGantt(
  segs: Segment[],
  score: Score,
  workdays: string[],
  dayRange: [number, number] | null,
) {
  const from = dayRange?.[0] ?? 0;
  const to = dayRange?.[1] ?? (segs.length ? Math.max(...segs.map((s) => s.day_idx)) : 0);
  const rangeSegs = segs.filter((s) => s.day_idx >= from && s.day_idx <= to);
  const lines: string[] = [];

  // Section 1: Segments
  lines.push("--- SEGMENTOS ---");
  lines.push(
    "Máquina,Dia,Data,Turno,Ferramenta,SKU,Quantidade,Setup(min),Produção(min),Início(min),Fim(min),EDD,Continuação,Gémeos,Twin_SKU_1,Twin_Qty_1,Twin_SKU_2,Twin_Qty_2",
  );
  const sorted = [...rangeSegs].sort(
    (a, b) => a.day_idx - b.day_idx || a.machine_id.localeCompare(b.machine_id) || a.start_min - b.start_min,
  );
  for (const s of sorted) {
    const date = workdays[s.day_idx] ?? "";
    lines.push(
      [
        s.machine_id, s.day_idx, date, s.shift, s.tool_id,
        `"${s.sku}"`, s.qty, s.setup_min.toFixed(1), s.prod_min.toFixed(1),
        s.start_min, s.end_min, s.edd,
        s.is_continuation ? "Sim" : "Não",
        s.twin_outputs ? "Sim" : "Não",
        s.twin_outputs ? `"${s.twin_outputs[0]?.[1] ?? ""}"` : "",
        s.twin_outputs ? (s.twin_outputs[0]?.[2] ?? 0) : "",
        s.twin_outputs ? `"${s.twin_outputs[1]?.[1] ?? ""}"` : "",
        s.twin_outputs ? (s.twin_outputs[1]?.[2] ?? 0) : "",
      ].join(","),
    );
  }

  // Section 2: Daily summary with logic
  lines.push("");
  lines.push("--- RESUMO POR DIA ---");
  lines.push("Dia,Data,Máquina,Ferramentas,Setups,Produção(min),Utilização(%),Peças,Lógica");
  for (let d = from; d <= to; d++) {
    const daySegs = rangeSegs.filter((s) => s.day_idx === d);
    const byMachine: Record<string, Segment[]> = {};
    for (const s of daySegs) (byMachine[s.machine_id] ??= []).push(s);
    const date = workdays[d] ?? "";
    for (const [mid, mSegs] of Object.entries(byMachine).sort()) {
      const tools = [...new Set(mSegs.map((s) => s.tool_id))];
      const setups = mSegs.filter((s) => s.setup_min > 0).length;
      const prodMin = mSegs.reduce((a, s) => a + s.prod_min + s.setup_min, 0);
      const util = Math.round((prodMin / DAY_CAP) * 100);
      const pcs = mSegs.reduce((a, s) => a + s.qty, 0);
      const logic = buildDayLogic(mSegs, d);
      lines.push(
        [mid, d, date, `"${tools.join(";")}"`, setups, prodMin.toFixed(0), util, pcs, `"${logic}"`].join(","),
      );
    }
  }

  // Section 3: KPIs
  lines.push("");
  lines.push("--- KPIs ---");
  lines.push("OTD,OTD-D,Atrasos,Setups,Earliness");
  lines.push(
    [
      `${score.otd?.toFixed(1)}%`,
      `${score.otd_d?.toFixed(1)}%`,
      score.tardy_count,
      score.setups,
      `${score.earliness_avg_days?.toFixed(1)}d`,
    ].join(","),
  );

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `gantt_dia${from}-${to}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Styles ───────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  background: T.elevated,
  border: `1px solid ${T.border}`,
  color: T.primary,
  borderRadius: 8,
  padding: "6px 12px",
  fontSize: 12,
  fontFamily: T.mono,
  outline: "none",
};

const smallInputStyle: React.CSSProperties = {
  ...inputStyle,
  width: 48,
  padding: "4px 6px",
  textAlign: "center" as const,
};

const btnStyle = (active: boolean): React.CSSProperties => ({
  background: active ? T.elevated : "transparent",
  border: "none",
  color: active ? T.primary : T.tertiary,
  padding: "4px 10px",
  fontSize: 11,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "inherit",
  borderRadius: 6,
  margin: 1,
  transition: "all 0.15s",
});

// ── Component ────────────────────────────────────────────────

export function GanttPage() {
  const segments = useDataStore((s) => s.segments);
  const score = useDataStore((s) => s.score);
  const config = useDataStore((s) => s.config);
  const learning = useDataStore((s) => s.learning);

  const machines = useMemo(() => {
    if (!config?.machines) return FALLBACK_MACHINES;
    return Object.entries(config.machines)
      .filter(([, m]) => (m as any).active !== false)
      .map(([id]) => id)
      .sort();
  }, [config]);

  const [view, setView] = useState<"gantt" | "tabela">("gantt");
  const [sel, setSel] = useState<Segment | null>(null);
  const [skuFilter, setSkuFilter] = useState("");
  const [dayW, setDayW] = useState(DEFAULT_DAY_W);
  const [dayRange, setDayRange] = useState<[number, number] | null>(null);
  const [workdays, setWorkdays] = useState<string[]>([]);
  const [rangeFrom, setRangeFrom] = useState("");
  const [rangeTo, setRangeTo] = useState("");
  const [currentDay, setCurrentDay] = useState(0);
  const [currentDayInitialized, setCurrentDayInitialized] = useState(false);

  const isSingleDay = dayRange !== null && dayRange[0] === dayRange[1];

  useEffect(() => {
    if (isSingleDay) setCurrentDay(dayRange![0]);
  }, [isSingleDay, dayRange]);

  useEffect(() => {
    getWorkdays().then(setWorkdays).catch(() => {});
  }, []);

  const minDay = useMemo(() => {
    if (!segments?.length) return 0;
    return Math.min(...segments.map((s) => s.day_idx));
  }, [segments]);

  // Initialize currentDay to minDay on first load
  useEffect(() => {
    if (!currentDayInitialized && segments?.length) {
      setCurrentDay(minDay);
      setCurrentDayInitialized(true);
    }
  }, [minDay, segments, currentDayInitialized]);

  const nDays = useMemo(() => {
    if (!segments?.length) return 14;
    return Math.max(...segments.map((s) => s.day_idx)) + 1;
  }, [segments]);

  const filtered = useMemo(() => {
    if (!segments) return [];
    const q = skuFilter.toLowerCase();
    return q
      ? segments.filter((s) => s.sku.toLowerCase().includes(q) || s.tool_id.toLowerCase().includes(q))
      : segments;
  }, [segments, skuFilter]);

  const visibleDays = useMemo(() => {
    if (!dayRange) return Array.from({ length: nDays - minDay }, (_, i) => minDay + i);
    return Array.from({ length: dayRange[1] - dayRange[0] + 1 }, (_, i) => dayRange[0] + i);
  }, [nDays, minDay, dayRange]);

  const visibleSegs = useMemo(() => {
    if (!dayRange) return filtered;
    return filtered.filter((s) => s.day_idx >= dayRange[0] && s.day_idx <= dayRange[1]);
  }, [filtered, dayRange]);

  const rangeOffset = dayRange?.[0] ?? minDay;

  // Machine utilization (visible range)
  const utilization = useMemo(() => {
    const segs = visibleSegs;
    if (!segs.length) return {};
    const totals: Record<string, number> = {};
    for (const s of segs) {
      totals[s.machine_id] = (totals[s.machine_id] || 0) + s.prod_min + s.setup_min;
    }
    const nVisible = visibleDays.length;
    const result: Record<string, number> = {};
    for (const m of machines) {
      result[m] = Math.round(((totals[m] || 0) / (nVisible * DAY_CAP)) * 100);
    }
    return result;
  }, [visibleSegs, visibleDays.length, machines]);

  // Day detail (computed from segments when zoomed to single day)
  const dayDetail = useMemo(() => {
    if (!isSingleDay || !segments) return null;
    const dayIdx = dayRange![0];
    const daySegs = segments.filter((s) => s.day_idx === dayIdx);
    if (!daySegs.length) return { machineDetails: [], allEdds: [], totalSegs: 0 };

    const byMachine: Record<string, Segment[]> = {};
    for (const s of daySegs) (byMachine[s.machine_id] ??= []).push(s);

    const machineDetails = Object.entries(byMachine)
      .sort()
      .map(([mid, segs]) => {
        const sorted = [...segs].sort((a, b) => a.start_min - b.start_min);
        const tools = [...new Set(sorted.map((s) => s.tool_id))];
        const setupSegs = sorted.filter((s) => s.setup_min > 0);
        const totalProd = sorted.reduce((a, s) => a + s.prod_min, 0);
        const totalSetup = sorted.reduce((a, s) => a + s.setup_min, 0);
        const totalPcs = sorted.reduce((a, s) => a + s.qty, 0);
        const util = Math.round(((totalProd + totalSetup) / DAY_CAP) * 100);
        const eddsHere = sorted.filter((s) => s.edd === dayIdx);
        const twins = sorted.filter((s) => s.twin_outputs);
        return { mid, segs: sorted, tools, setupSegs, totalProd, totalSetup, totalPcs, util, eddsHere, twins };
      });

    const allEdds = daySegs.filter((s) => s.edd === dayIdx);
    return { machineDetails, allEdds, totalSegs: daySegs.length };
  }, [isSingleDay, dayRange, segments]);

  // Range presets
  const setPreset = (name: string) => {
    if (name === "tudo") {
      setDayRange(null);
      setRangeFrom("");
      setRangeTo("");
    } else if (name === "1dia") {
      const d = currentDay;
      setDayRange([d, d]);
      setRangeFrom(String(d));
      setRangeTo(String(d));
    } else {
      const end = name === "semana" ? 4 : name === "2sem" ? 9 : 19;
      const r: [number, number] = [minDay, Math.min(end, nDays - 1)];
      setDayRange(r);
      setRangeFrom(String(r[0]));
      setRangeTo(String(r[1]));
    }
  };

  const applyCustomRange = () => {
    const f = parseInt(rangeFrom);
    const t = parseInt(rangeTo);
    if (!isNaN(f) && !isNaN(t) && f >= minDay && t >= f && t < nDays) {
      setDayRange([f, t]);
    }
  };

  if (!segments) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header row 1: KPIs */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 24 }}>
          {score &&
            [
              { l: "OTD", v: `${score.otd?.toFixed(1)}%`, c: (score.otd ?? 0) >= 98 ? T.green : T.orange },
              { l: "OTD-D", v: `${score.otd_d?.toFixed(1)}%`, c: (score.otd_d ?? 0) >= 95 ? T.green : T.orange },
              { l: "Atrasos", v: score.tardy_count, c: score.tardy_count > 0 ? T.red : T.green },
              { l: "Setups", v: score.setups },
              { l: "Antecipação", v: `${score.earliness_avg_days?.toFixed(1)}d` },
            ].map((k, i) => (
              <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <span style={{ fontSize: 12, color: T.tertiary }}>{k.l}</span>
                <span style={{ fontSize: 14, fontWeight: 600, color: k.c || T.primary, fontFamily: T.mono }}>
                  {k.v}
                </span>
              </div>
            ))}
          {learning?.optimized && (() => {
            const badgeColor =
              learning.confidence === "high" ? T.green :
              learning.confidence === "medium" ? T.orange : T.secondary;
            const label =
              learning.confidence === "high" ? "alta" :
              learning.confidence === "medium" ? "média" : "baixa";
            const imp = learning.improvement;
            return (
              <Pill color={badgeColor}>
                <Dot color={badgeColor} size={5} />
                <span style={{ marginLeft: 4 }}>
                  Optimizado ({label} confiança) — {learning.n_trials} trials
                  {imp?.earliness_delta != null && imp.earliness_delta !== 0 && `, earliness ${imp.earliness_delta > 0 ? "+" : ""}${imp.earliness_delta}d`}
                  {imp?.setups_delta != null && imp.setups_delta !== 0 && `, setups ${imp.setups_delta > 0 ? "+" : ""}${imp.setups_delta}`}
                </span>
              </Pill>
            );
          })()}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={skuFilter}
            onChange={(e) => setSkuFilter(e.target.value)}
            placeholder="Filtrar SKU/Tool..."
            style={{ ...inputStyle, width: 140 }}
          />
          <div
            style={{
              display: "flex",
              background: T.card,
              borderRadius: 8,
              border: `1px solid ${T.border}`,
              overflow: "hidden",
            }}
          >
            {(["gantt", "tabela"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} style={btnStyle(view === v)}>
                {v === "gantt" ? "Gantt" : "Tabela"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Header row 2: Zoom + Range + Export */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        {/* Zoom slider */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 11, color: T.tertiary }}>Zoom</span>
          <input
            type="range"
            min={50}
            max={300}
            value={dayW}
            onChange={(e) => setDayW(Number(e.target.value))}
            style={{ width: 100, accentColor: T.blue }}
          />
          <span style={{ fontSize: 11, color: T.secondary, fontFamily: T.mono, minWidth: 32 }}>{dayW}px</span>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 20, background: T.border }} />

        {/* Range presets */}
        <div
          style={{
            display: "flex",
            background: T.card,
            borderRadius: 8,
            border: `1px solid ${T.border}`,
            overflow: "hidden",
          }}
        >
          {(
            [
              ["1dia", "1 Dia"],
              ["semana", "Semana"],
              ["2sem", "2 Sem"],
              ["mes", "Mês"],
              ["tudo", "Tudo"],
            ] as const
          ).map(([id, label]) => {
            const active =
              id === "tudo"
                ? !dayRange
                : id === "1dia"
                  ? isSingleDay
                  : id === "semana"
                    ? dayRange?.[0] === minDay && dayRange?.[1] === Math.min(4, nDays - 1)
                    : id === "2sem"
                      ? dayRange?.[0] === minDay && dayRange?.[1] === Math.min(9, nDays - 1)
                      : dayRange?.[0] === minDay && dayRange?.[1] === Math.min(19, nDays - 1);
            return (
              <button key={id} onClick={() => setPreset(id)} style={btnStyle(active)}>
                {label}
              </button>
            );
          })}
        </div>

        {/* Custom range inputs */}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 11, color: T.tertiary }}>De</span>
          <input
            value={rangeFrom}
            onChange={(e) => setRangeFrom(e.target.value)}
            onBlur={applyCustomRange}
            onKeyDown={(e) => e.key === "Enter" && applyCustomRange()}
            placeholder="0"
            style={smallInputStyle}
          />
          <span style={{ fontSize: 11, color: T.tertiary }}>a</span>
          <input
            value={rangeTo}
            onChange={(e) => setRangeTo(e.target.value)}
            onBlur={applyCustomRange}
            onKeyDown={(e) => e.key === "Enter" && applyCustomRange()}
            placeholder={String(nDays - 1)}
            style={smallInputStyle}
          />
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 20, background: T.border }} />

        {/* Export button */}
        <button
          onClick={() => score && exportGantt(segments, score, workdays, dayRange)}
          style={{
            ...inputStyle,
            cursor: "pointer",
            padding: "5px 14px",
            fontWeight: 500,
            background: T.blue + "18",
            border: `1px solid ${T.blue}44`,
            color: T.blue,
          }}
        >
          Exportar CSV
        </button>
      </div>

      {/* Utilization bars */}
      <Card style={{ padding: 16 }}>
        <div style={{ display: "flex", gap: 16 }}>
          {machines.map((m) => {
            const u = utilization[m] || 0;
            const c = u > 95 ? T.red : u > 85 ? T.orange : u > 70 ? T.blue : T.green;
            return (
              <div key={m} style={{ flex: 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, color: T.secondary }}>{m}</span>
                  <span style={{ fontSize: 11, color: c, fontWeight: 600, fontFamily: T.mono }}>{u}%</span>
                </div>
                <ProgressBar value={u} color={c} height={3} />
              </div>
            );
          })}
        </div>
      </Card>

      {view === "gantt" ? (
        <Card style={{ padding: 0, overflow: "auto" }}>
          {/* Single-day navigator */}
          {isSingleDay && (() => {
            const d = dayRange![0];
            const navPrev = () => { const n = Math.max(minDay, d - 1); setDayRange([n, n]); setRangeFrom(String(n)); setRangeTo(String(n)); };
            const navNext = () => { const n = Math.min(nDays - 1, d + 1); setDayRange([n, n]); setRangeFrom(String(n)); setRangeTo(String(n)); };
            return (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 16,
                  padding: "10px 24px",
                  borderBottom: `1px solid ${T.border}`,
                  background: T.card,
                }}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft" && d > minDay) navPrev();
                  if (e.key === "ArrowRight" && d < nDays - 1) navNext();
                }}
              >
                <button
                  onClick={navPrev}
                  disabled={d <= minDay}
                  style={{
                    background: "none",
                    border: `1px solid ${T.border}`,
                    borderRadius: 6,
                    color: d <= minDay ? T.tertiary : T.primary,
                    cursor: d <= minDay ? "default" : "pointer",
                    padding: "4px 10px",
                    fontSize: 14,
                    fontFamily: "inherit",
                    opacity: d <= minDay ? 0.4 : 1,
                  }}
                >
                  ‹
                </button>
                <div style={{ textAlign: "center", minWidth: 200 }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>
                    Dia {d}{d >= 0 && workdays[d] ? ` — ${fmtDate(workdays[d]).short}` : d < 0 ? " (Buffer)" : ""}
                  </div>
                  <div style={{ fontSize: 11, color: T.tertiary }}>
                    {d >= 0 && workdays[d] ? fmtDate(workdays[d]).dow : ""}
                    {" · "}{d - minDay + 1}/{nDays - minDay}
                  </div>
                </div>
                <button
                  onClick={navNext}
                  disabled={d >= nDays - 1}
                  style={{
                    background: "none",
                    border: `1px solid ${T.border}`,
                    borderRadius: 6,
                    color: d >= nDays - 1 ? T.tertiary : T.primary,
                    cursor: d >= nDays - 1 ? "default" : "pointer",
                    padding: "4px 10px",
                    fontSize: 14,
                    fontFamily: "inherit",
                    opacity: d >= nDays - 1 ? 0.4 : 1,
                  }}
                >
                  ›
                </button>
              </div>
            );
          })()}

          {/* Timeline header */}
          <div
            style={{
              display: "flex",
              borderBottom: `1px solid ${T.border}`,
              position: "sticky",
              top: 0,
              background: T.card,
              zIndex: 2,
            }}
          >
            <div
              style={{
                width: 72,
                flexShrink: 0,
                padding: "8px 16px",
                fontSize: 11,
                color: T.tertiary,
                borderRight: `1px solid ${T.border}`,
              }}
            >
              Máquina
            </div>
            {isSingleDay ? (
              /* Hour ticks for single-day */
              (() => {
                const totalW = Math.max(dayW * 4, 800);
                const ticks = Array.from({ length: 18 }, (_, i) => {
                  const min = DAY_START + i * 60;
                  const h = Math.floor(min / 60);
                  return { min, label: `${String(h % 24).padStart(2, "0")}:00` };
                });
                return (
                  <div style={{ position: "relative", minWidth: totalW, height: 32 }}>
                    {ticks.map((tick) => {
                      const x = ((tick.min - DAY_START) / DAY_CAP) * totalW;
                      return (
                        <div
                          key={tick.label}
                          style={{
                            position: "absolute",
                            left: x,
                            top: 0,
                            height: "100%",
                            display: "flex",
                            alignItems: "center",
                            borderLeft: tick.min === SHIFT_CHANGE
                              ? `1.5px solid ${T.orange}55`
                              : `1px solid ${T.border}`,
                          }}
                        >
                          <span style={{
                            fontSize: 9,
                            color: tick.min === SHIFT_CHANGE ? T.orange : T.tertiary,
                            fontFamily: T.mono,
                            marginLeft: 4,
                            whiteSpace: "nowrap",
                          }}>
                            {tick.label}
                            {tick.min === SHIFT_CHANGE ? " (turno B)" : ""}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })()
            ) : (
              /* Day columns for multi-day */
              visibleDays.map((i) => {
                const dt = i >= 0 && workdays[i] ? fmtDate(workdays[i]) : null;
                return (
                  <div
                    key={i}
                    onClick={() => { setDayRange([i, i]); setRangeFrom(String(i)); setRangeTo(String(i)); }}
                    title="Clica para ver detalhe do dia"
                    style={{
                      width: dayW,
                      flexShrink: 0,
                      padding: "6px 0",
                      textAlign: "center",
                      borderRight: `1px solid ${T.border}`,
                      cursor: "pointer",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = `${T.blue}08`)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <div style={{ fontSize: 10, color: i < 0 ? T.orange : T.secondary, fontFamily: T.mono }}>{dt?.short ?? `D${i}`}</div>
                    <div style={{ fontSize: 9, color: T.tertiary }}>{dt?.dow ?? (i < 0 ? "Buffer" : "")}</div>
                  </div>
                );
              })
            )}
          </div>

          {/* Machine lanes */}
          {(() => {
            const totalW = isSingleDay ? Math.max(dayW * 4, 800) : dayW * visibleDays.length;

            return machines.map((m) => {
              const machineSegs = visibleSegs.filter((s) => s.machine_id === m);
              const laneH = isSingleDay
                ? SINGLE_BAR_PAD + SINGLE_BAR_H + SINGLE_BAR_PAD
                : LANE_H;

              return (
                <div key={m} style={{ display: "flex", borderBottom: `1px solid ${T.border}` }}>
                  <div
                    style={{
                      width: 72,
                      flexShrink: 0,
                      padding: "0 16px",
                      display: "flex",
                      alignItems: "center",
                      fontSize: 12,
                      fontWeight: 600,
                      color: T.primary,
                      borderRight: `1px solid ${T.border}`,
                      fontFamily: T.mono,
                    }}
                  >
                    {m}
                  </div>
                  <div style={{ position: "relative", height: laneH, flex: 1, minWidth: totalW }}>
                    {isSingleDay ? (
                      /* Hour grid lines for single-day */
                      Array.from({ length: 18 }, (_, i) => {
                        const min = DAY_START + i * 60;
                        const x = ((min - DAY_START) / DAY_CAP) * totalW;
                        return (
                          <div
                            key={`h${i}`}
                            style={{
                              position: "absolute",
                              left: x,
                              top: 0,
                              bottom: 0,
                              width: min === SHIFT_CHANGE ? 1.5 : 0.5,
                              background: min === SHIFT_CHANGE ? `${T.orange}33` : T.border,
                            }}
                          />
                        );
                      })
                    ) : (
                      /* Day grid lines + shift separators for multi-day */
                      <>
                        {visibleDays.map((_, idx) => (
                          <div
                            key={`g${idx}`}
                            style={{
                              position: "absolute",
                              left: idx * dayW,
                              top: 0,
                              bottom: 0,
                              width: 0.5,
                              background: T.border,
                            }}
                          />
                        ))}
                        {visibleDays.map((_, idx) => (
                          <div
                            key={`s${idx}`}
                            style={{
                              position: "absolute",
                              left: idx * dayW + ((SHIFT_CHANGE - DAY_START) / DAY_CAP) * dayW,
                              top: 0,
                              bottom: 0,
                              width: 0.5,
                              background: T.border,
                              borderLeft: `1px dashed ${T.border}`,
                            }}
                          />
                        ))}
                      </>
                    )}
                    {/* Segments */}
                    {machineSegs.map((s) => {
                      const left = isSingleDay
                        ? ((s.start_min - DAY_START) / DAY_CAP) * totalW
                        : (s.day_idx - rangeOffset) * dayW + ((s.start_min - DAY_START) / DAY_CAP) * dayW;
                      const width = isSingleDay
                        ? Math.max(((s.end_min - s.start_min) / DAY_CAP) * totalW, 40)
                        : Math.max(((s.end_min - s.start_min) / DAY_CAP) * dayW, 3);
                      const col = toolColor(s.tool_id);
                      const top = isSingleDay ? SINGLE_BAR_PAD : 10;
                      const barH = isSingleDay ? SINGLE_BAR_H : 40;
                      return (
                        <div
                          key={`${s.lot_id}-${s.day_idx}-${s.start_min}`}
                          title={`${s.tool_id} | ${s.sku} | ${s.qty.toLocaleString()} pç | ${fmtMin(s.start_min)}–${fmtMin(s.end_min)} | EDD d${s.edd}${s.twin_outputs ? " | Twin" : ""}`}
                          onClick={() => setSel(s)}
                          style={{
                            position: "absolute",
                            left,
                            top,
                            width,
                            height: barH,
                            background: `${col}18`,
                            borderRadius: 5,
                            cursor: "pointer",
                            border: `1px solid ${col}55`,
                            transition: "all 0.15s",
                            borderLeft: s.is_continuation ? `2px dashed ${col}66` : undefined,
                            overflow: "hidden",
                          }}
                        >
                          {/* Setup overlay — behind text */}
                          {s.setup_min > 0 && (
                            <div
                              style={{
                                position: "absolute",
                                left: 0,
                                top: 0,
                                bottom: 0,
                                zIndex: 0,
                                width: Math.max((s.setup_min / (s.end_min - s.start_min)) * width, 1.5),
                                background: `${col}30`,
                                backgroundImage: `repeating-linear-gradient(-45deg, transparent, transparent 3px, ${col}15 3px, ${col}15 6px)`,
                                borderRight: `1px dashed ${col}44`,
                              }}
                            />
                          )}
                          {/* Text content — above setup */}
                          {isSingleDay ? (
                            <div style={{
                              position: "relative",
                              zIndex: 1,
                              display: "flex",
                              flexDirection: "column",
                              gap: 1,
                              padding: "6px 8px",
                              overflow: "hidden",
                              height: "100%",
                              justifyContent: "center",
                            }}>
                              <span style={{ fontSize: 10, color: `${col}dd`, fontWeight: 700, fontFamily: T.mono, lineHeight: 1.3 }}>
                                {s.sku}
                                {s.setup_min > 0 ? ` ⚙${s.setup_min.toFixed(0)}m` : ""}
                              </span>
                              {width > 50 && (
                                <span style={{
                                  fontSize: 9,
                                  color: T.secondary,
                                  lineHeight: 1.3,
                                  whiteSpace: "nowrap",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  maxWidth: width - 16,
                                }}>
                                  {s.twin_outputs
                                    ? s.twin_outputs.map(([, sku, qty]: [string, string, number]) => `${sku}: ${qty.toLocaleString()}`).join(" + ")
                                    : `${s.sku} · ${s.qty.toLocaleString()} pç`}
                                </span>
                              )}
                              {width > 100 && (
                                <span style={{ fontSize: 8, color: T.tertiary, lineHeight: 1.3 }}>
                                  {s.prod_min.toFixed(0)}m prod · {s.shift}
                                </span>
                              )}
                            </div>
                          ) : (
                            width > 28 && (
                              <div style={{
                                position: "relative",
                                zIndex: 1,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                width: "100%",
                                height: "100%",
                              }}>
                                <span style={{ fontSize: 8, color: `${col}cc`, fontWeight: 600, fontFamily: T.mono }}>
                                  {width > 55 ? s.sku : s.tool_id}
                                </span>
                              </div>
                            )
                          )}
                          {/* Twin badge */}
                          {s.twin_outputs && (
                            <span
                              style={{
                                position: "absolute",
                                top: 1,
                                right: 2,
                                zIndex: 2,
                                fontSize: isSingleDay ? 9 : 7,
                                fontWeight: 700,
                                color: `${col}cc`,
                                background: `${col}22`,
                                borderRadius: 3,
                                padding: "0 2px",
                              }}
                            >
                              T
                            </span>
                          )}
                        </div>
                      );
                    })}
                    {/* EDD markers */}
                    {(() => {
                      const edds = new Set<number>();
                      machineSegs.forEach((s) => edds.add(s.edd));
                      if (isSingleDay) {
                        const hasDeadline = machineSegs.some((s) => s.edd === dayRange![0]);
                        return hasDeadline ? (
                          <div style={{
                            position: "absolute",
                            right: 4,
                            top: 2,
                            fontSize: 9,
                            color: T.red,
                            fontWeight: 700,
                            zIndex: 20,
                          }}>
                            DEADLINE
                          </div>
                        ) : null;
                      }
                      return [...edds]
                        .filter((edd) => edd >= rangeOffset && edd < rangeOffset + visibleDays.length)
                        .map((edd) => (
                          <div
                            key={`edd-${edd}`}
                            style={{
                              position: "absolute",
                              left: (edd - rangeOffset) * dayW + dayW / 2,
                              top: 0,
                              bottom: 0,
                              width: 0,
                              borderLeft: `1px dashed ${T.red}55`,
                            }}
                          />
                        ));
                    })()}
                  </div>
                </div>
              );
            });
          })()}
        </Card>
      ) : (
        /* Table view */
        <Card style={{ padding: 0, overflow: "auto", maxHeight: 600 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ position: "sticky", top: 0, background: T.card }}>
                {["Máq", "Dia", "Data", "Turno", "Tool", "SKU", "Qty", "Setup", "Prod", "EDD"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 14px",
                      textAlign: "left",
                      fontSize: 11,
                      color: T.tertiary,
                      fontWeight: 500,
                      borderBottom: `1px solid ${T.border}`,
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleSegs.slice(0, 200).map((s, i) => {
                const dt = workdays[s.day_idx] ? fmtDate(workdays[s.day_idx]) : null;
                return (
                  <tr
                    key={i}
                    style={{ borderBottom: `1px solid ${T.border}`, cursor: "pointer" }}
                    onClick={() => setSel(s)}
                  >
                    <td style={{ padding: "8px 14px", fontSize: 12, fontWeight: 600, color: T.primary, fontFamily: T.mono }}>{s.machine_id}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.secondary }}>{s.day_idx}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.tertiary }}>{dt?.short ?? ""}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.tertiary }}>{s.shift}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: toolColor(s.tool_id), fontWeight: 500 }}>{s.tool_id}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.secondary, fontFamily: T.mono }}>{s.sku}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.secondary }}>{s.qty}</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: s.setup_min > 0 ? T.orange : T.tertiary }}>{s.setup_min.toFixed(0)}m</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.secondary }}>{s.prod_min.toFixed(0)}m</td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: T.secondary }}>{s.edd}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {/* Day detail panel (shown below Gantt when single-day) */}
      {isSingleDay && view === "gantt" && dayDetail && dayDetail.totalSegs > 0 && (
        <Card style={{ padding: 20 }}>
          {/* Summary row */}
          <div style={{ display: "flex", gap: 16, marginBottom: 16, fontSize: 12, color: T.secondary }}>
            <span>{dayDetail.totalSegs} segmentos</span>
            <span style={{ color: T.border }}>|</span>
            <span style={{ color: dayDetail.allEdds.length > 0 ? T.orange : T.secondary }}>
              {dayDetail.allEdds.length} deadline{dayDetail.allEdds.length !== 1 ? "s" : ""}
            </span>
            <span style={{ color: T.border }}>|</span>
            <span>
              {Math.round(dayDetail.machineDetails.reduce((a, m) => a + m.util, 0) / dayDetail.machineDetails.length)}% utilização média
            </span>
          </div>

          {/* Per-machine breakdown */}
          {dayDetail.machineDetails.map((md) => (
            <div key={md.mid} style={{ borderBottom: `1px solid ${T.border}`, paddingBottom: 14, marginBottom: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: T.mono, minWidth: 56 }}>
                  {md.mid}
                </span>
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: T.mono,
                  color: md.util > 95 ? T.red : md.util > 85 ? T.orange : md.util > 70 ? T.blue : T.green,
                }}>
                  {md.util}%
                </span>
                <div style={{ flex: 1, height: 3, background: T.elevated, borderRadius: 2, overflow: "hidden" }}>
                  <div style={{
                    width: `${Math.min(md.util, 100)}%`,
                    height: "100%",
                    background: md.util > 95 ? T.red : md.util > 85 ? T.orange : md.util > 70 ? T.blue : T.green,
                    borderRadius: 2,
                  }} />
                </div>
                <span style={{ fontSize: 11, color: T.tertiary, fontFamily: T.mono }}>
                  {md.totalPcs.toLocaleString()} pç
                </span>
              </div>

              {md.tools.map((toolId) => {
                const toolSegs = md.segs.filter((s) => s.tool_id === toolId);
                const toolSetup = toolSegs.find((s) => s.setup_min > 0);
                const isCont = toolSegs.every((s) => s.is_continuation);
                return (
                  <div key={toolId} style={{ marginLeft: 16, marginBottom: 6 }}>
                    <div style={{ fontSize: 12, color: toolColor(toolId), fontWeight: 500, marginBottom: 2 }}>
                      {toolId}
                      {toolSetup
                        ? ` (setup ${toolSetup.setup_min.toFixed(0)}min)`
                        : isCont
                          ? " (sem setup — continuação)"
                          : ""}
                    </div>
                    {toolSegs.map((s, si) => (
                      <div key={si} style={{ fontSize: 11, color: T.secondary, marginLeft: 8, lineHeight: 1.6 }}>
                        → {s.qty.toLocaleString()} pç ({s.sku})
                        {s.twin_outputs && (
                          <span style={{
                            fontSize: 9,
                            fontWeight: 700,
                            color: T.blue,
                            background: `${T.blue}15`,
                            borderRadius: 3,
                            padding: "0 3px",
                            marginLeft: 4,
                          }}>
                            T
                          </span>
                        )}
                        {s.twin_outputs && (
                          <div style={{ marginLeft: 12, fontSize: 10, color: T.tertiary }}>
                            {s.twin_outputs.map(([_opId, sku, qty]: [string, string, number], i: number) => (
                              <div key={i}>↳ {sku}: {qty.toLocaleString()} pç{qty === 0 ? " (sem produção)" : ""}</div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                );
              })}

              {md.eddsHere.length > 0 && (
                <div style={{ fontSize: 11, color: T.orange, marginLeft: 16, marginTop: 4 }}>
                  ⚠ {md.eddsHere.length} deadline{md.eddsHere.length !== 1 ? "s" : ""} hoje
                </div>
              )}
            </div>
          ))}

          {/* Logic summary */}
          <div style={{ marginTop: 8, padding: "10px 12px", background: T.elevated, borderRadius: 8, fontSize: 11, color: T.secondary, lineHeight: 1.6 }}>
            <span style={{ fontWeight: 600, color: T.tertiary }}>Lógica: </span>
            {buildDayLogic(segments!.filter((s) => s.day_idx === dayRange![0]), dayRange![0])}
          </div>
        </Card>
      )}

      {/* Segment detail modal */}
      {sel && (
        <Modal title="Segmento" onClose={() => setSel(null)}>
          {[
            ["Máquina", sel.machine_id],
            ["Dia", `${sel.day_idx}${workdays[sel.day_idx] ? ` (${fmtDate(workdays[sel.day_idx]).short})` : ""}`],
            ["Turno", sel.shift],
            ["Ferramenta", sel.tool_id],
            ["SKU", sel.sku],
            ["Quantidade", sel.qty],
            ["Setup", `${sel.setup_min.toFixed(1)} min`],
            ["Produção", `${sel.prod_min.toFixed(1)} min`],
            ["Início", fmtMin(sel.start_min)],
            ["Fim", fmtMin(sel.end_min)],
            ["EDD", `Dia ${sel.edd}${workdays[sel.edd] ? ` (${fmtDate(workdays[sel.edd]).short})` : ""}`],
            ["Lot", sel.lot_id],
            ["Continuação", sel.is_continuation ? "Sim" : "Não"],
            ["Gémeos", sel.twin_outputs ? "Sim" : "Não"],
            ...(sel.twin_outputs
              ? sel.twin_outputs.map(([_opId, sku, qty]: [string, string, number], i: number) => [
                  `  Twin ${i + 1}`,
                  `${qty.toLocaleString()} pç (${sku})`,
                ])
              : []),
          ].map(([k, v]) => (
            <div
              key={String(k)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "10px 0",
                borderBottom: `1px solid ${T.border}`,
              }}
            >
              <span style={{ fontSize: 13, color: T.secondary }}>{k}</span>
              <span style={{ fontSize: 13, color: T.primary, fontWeight: 500, fontFamily: T.mono }}>{String(v)}</span>
            </div>
          ))}
        </Modal>
      )}
    </div>
  );
}
