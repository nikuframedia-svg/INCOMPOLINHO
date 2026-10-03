import { useCallback, useMemo, useState } from "react";
import { getCapacity } from "../api/endpoints";
import type { CapacityItem, CapacityResponse } from "../api/types";
import { T } from "../theme/tokens";
import { Card } from "./ui/Card";
import { formatDuration } from "../lib/duration";
import { usePlanQuery } from "../hooks/usePlanQuery";

const toggleStyle = (active: boolean): React.CSSProperties => ({
  background: active ? T.elevated : "transparent",
  border: "none",
  borderRadius: 6,
  color: active ? T.primary : T.tertiary,
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 11,
  fontWeight: active ? 600 : 400,
  padding: "5px 10px",
});

function shortDate(value: string) {
  if (!value) return "—";
  const parts = value.split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}` : value;
}

function workdayCount(item: unknown) {
  const row = item as { workday_count?: number; day_indices?: number[] };
  return Number(row.workday_count ?? row.day_indices?.length ?? 0);
}

type TimelineItem = Pick<CapacityItem, "bucket" | "date_from" | "date_to"> & {
  label?: string;
  day_indices?: number[];
  workday_count?: number;
};

function timelineLabel(item: TimelineItem) {
  if (item.bucket.includes("W")) {
    return `${item.bucket} · ${workdayCount(item)}d`;
  }
  return shortDate(item.label || item.date_from);
}

function timelineSubLabel(item: TimelineItem) {
  if (item.bucket.includes("W")) {
    return `${shortDate(item.date_from)}–${shortDate(item.date_to)}`;
  }
  return item.date_from;
}

function CapacityTimeline({
  items,
  title = "Máquina",
  leftWidth = 92,
  itemWidth = 156,
}: {
  items: TimelineItem[];
  title?: string;
  leftWidth?: number;
  itemWidth?: number;
}) {
  if (!items.length) return null;
  return (
    <div style={{ display: "flex", minWidth: "max-content", position: "sticky", top: 0, zIndex: 4 }}>
      <div
        style={{
          width: leftWidth,
          flexShrink: 0,
          position: "sticky",
          left: 0,
          zIndex: 5,
          background: T.card,
          borderRight: `1px solid ${T.border}`,
          borderBottom: `1px solid ${T.border}`,
          padding: "9px 14px",
          color: T.tertiary,
          fontSize: 10,
          fontWeight: 700,
        }}
      >
        {title}
      </div>
      {items.map((item) => (
        <div
          key={`timeline-${item.bucket}`}
          title={`${item.date_from} — ${item.date_to}`}
          style={{
            width: itemWidth,
            flexShrink: 0,
            borderRight: `1px solid ${T.border}`,
            borderBottom: `1px solid ${T.border}`,
            background: T.card,
            padding: "8px 11px",
          }}
        >
          <div style={{ color: T.primary, fontSize: 11, fontWeight: 700, fontFamily: T.mono }}>
            {timelineLabel(item)}
          </div>
          <div style={{ color: T.tertiary, fontSize: 9, marginTop: 2, fontFamily: T.mono }}>
            {timelineSubLabel(item)}
          </div>
        </div>
      ))}
    </div>
  );
}

function CapacityCell({ item }: { item: CapacityItem }) {
  const noCapacity = item.load_min > 0 && item.cap_min <= 0;
  const closed = item.cap_min === 0 && !noCapacity;
  const utilization = item.util_pct ?? 0;
  const noLoad = item.load_min <= 0 && item.cap_min > 0;
  const basis = Math.max(item.cap_min, item.load_min, 1);
  const prodWidth = item.prod_min / basis * 100;
  const setupWidth = item.setup_min / basis * 100;
  const complete = !item.overload && item.cap_min > 0 && utilization >= 99.95;
  const color = item.overload || noCapacity ? T.red : complete || utilization >= 85 ? T.orange : T.blue;
  return (
    <div style={{
      width: 156,
      flexShrink: 0,
      padding: "10px 11px",
      borderRight: `1px solid ${T.border}`,
      background: closed
        ? `repeating-linear-gradient(135deg, ${T.elevated}, ${T.elevated} 7px, ${T.border} 7px, ${T.border} 8px)`
        : noLoad
          ? `${T.tertiary}10`
        : "transparent",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 6, marginBottom: 7 }}>
        <span title={`${item.date_from} — ${item.date_to}`} style={{ color: closed ? T.tertiary : T.secondary, fontSize: 10, fontFamily: T.mono }}>
          {timelineLabel(item)}
        </span>
        <span style={{ color, fontSize: 10, fontWeight: 700, fontFamily: T.mono }}>
          {noCapacity ? "Sem capacidade" : closed ? "Fechado" : noLoad ? "Sem carga" : complete ? "100% · completa" : `${utilization.toFixed(0)}%`}
        </span>
      </div>
      <div title="Cinzento: sem carga restante; vermelho: carga > capacidade" style={{ height: 8, borderRadius: 4, background: "#D4DDDA", overflow: "hidden", display: "flex" }}>
        <div title={`${item.prod_min} min produção`} style={{ width: `${prodWidth}%`, background: item.overload ? T.red : T.blue }} />
        <div title={`${item.setup_min} min setup`} style={{ width: `${setupWidth}%`, background: T.orange }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 7, color: T.tertiary, fontSize: 9, fontFamily: T.mono }}>
        <span>{formatDuration(item.load_min)}/{formatDuration(item.cap_min)}</span>
        <span style={{ color: item.n_setups > 0 ? T.orange : T.tertiary, fontWeight: item.n_setups > 0 ? 700 : 400 }}>
          {item.n_setups} setup{item.n_setups === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}

export function CapacityView() {
  const [granularity, setGranularity] = useState<"day" | "week">("day");
  const loadCapacity = useCallback(() => getCapacity(granularity), [granularity]);
  const { data, error } = usePlanQuery(granularity, loadCapacity);

  const changeGranularity = (next: "day" | "week") => {
    if (next === granularity) return;
    setGranularity(next);
  };

  const rows = useMemo(() => {
    const grouped = new Map<string, CapacityItem[]>();
    for (const item of data?.items ?? []) {
      const entries = grouped.get(item.machine_id) ?? [];
      entries.push(item);
      grouped.set(item.machine_id, entries);
    }
    return [...grouped.entries()];
  }, [data]);
  const timelineItems = rows[0]?.[1] ?? [];
  const operatorRows = useMemo(() => {
    const grouped = new Map<string, NonNullable<CapacityResponse["operators"]>>();
    for (const item of data?.operators ?? []) {
      const key = `${item.group} · turno ${item.shift}`;
      grouped.set(key, [...(grouped.get(key) ?? []), item]);
    }
    return [...grouped.entries()];
  }, [data]);

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div>
          <div style={{ color: T.primary, fontSize: 13, fontWeight: 700 }}>Carga e capacidade</div>
          <div style={{ color: T.tertiary, fontSize: 10, marginTop: 2 }}>
            Azul: produção · laranja: setup · cinzento: sem carga · tracejado: fechado · vermelho: carga acima da capacidade (carga &gt; capacidade) · 100% completa não é erro
          </div>
        </div>
        <div style={{ display: "flex", border: `1px solid ${T.border}`, background: T.card, borderRadius: 8, padding: 1 }}>
          <button onClick={() => changeGranularity("day")} style={toggleStyle(granularity === "day")}>Dia</button>
          <button onClick={() => changeGranularity("week")} style={toggleStyle(granularity === "week")}>Semana</button>
        </div>
      </div>
      {error && <div style={{ color: T.red, fontSize: 12 }}>{error}</div>}
      {!data && !error && <div style={{ color: T.secondary, padding: 24 }}>A calcular capacidade…</div>}
      {data && (
        <>
        <Card style={{ padding: 0, overflow: "auto" }}>
          <CapacityTimeline items={timelineItems} />
          {rows.map(([machine, items], rowIndex) => (
            <div key={machine} style={{ display: "flex", borderTop: rowIndex > 0 ? `1px solid ${T.border}` : undefined, minWidth: "max-content" }}>
              <div style={{ width: 92, flexShrink: 0, position: "sticky", left: 0, zIndex: 2, background: T.card, borderRight: `1px solid ${T.border}`, padding: "12px 14px", color: T.primary, fontFamily: T.mono, fontSize: 11, fontWeight: 700 }}>
                {machine}
              </div>
              {items.map((item) => <CapacityCell key={`${machine}-${item.bucket}`} item={item} />)}
            </div>
          ))}
        </Card>
        <div style={{ color: T.primary, fontSize: 12, fontWeight: 700, marginTop: 4 }}>Operadores por grupo e turno</div>
        <Card style={{ padding: 0, overflow: "auto" }}>
          <CapacityTimeline
            items={operatorRows[0]?.[1] ?? []}
            title="Grupo/turno"
            leftWidth={145}
            itemWidth={142}
          />
          {operatorRows.map(([label, items], rowIndex) => (
            <div key={label} style={{ display: "flex", minWidth: "max-content", borderTop: rowIndex ? `1px solid ${T.border}` : undefined }}>
              <div style={{ width: 145, flexShrink: 0, position: "sticky", left: 0, zIndex: 2, background: T.card, borderRight: `1px solid ${T.border}`, padding: "11px 12px", color: T.primary, fontSize: 10, fontWeight: 700 }}>{label}</div>
              {items.map((item) => {
                const noCapacity = item.load_operator_min > 0 && item.capacity_operator_min <= 0;
                const utilization = item.util_pct ?? 0;
                const color = item.overload || noCapacity ? T.red : utilization > 85 ? T.orange : utilization > 65 ? T.blue : T.green;
                const alpha = noCapacity ? 55 : Math.max(12, Math.min(55, Math.round(utilization / 2)));
                const peakLabel = item.peak_required === undefined
                  ? ""
                  : ` · pico ${item.peak_required}/${item.min_available ?? 0}`;
                return (
                  <div key={`${label}-${item.bucket}`} title={`${item.load_operator_min.toFixed(0)} / ${item.capacity_operator_min.toFixed(0)} operador-min${peakLabel}`} style={{ width: 142, flexShrink: 0, padding: "10px 11px", borderRight: `1px solid ${T.border}`, background: `${color}${alpha.toString(16).padStart(2, "0")}` }}>
                    <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 4, color: T.secondary, fontSize: 9 }}>
                      <span>{item.bucket.includes("W") ? `${item.bucket} · ${workdayCount(item)}d` : shortDate(item.date_from)}</span>
                      <strong style={{ color }}>{noCapacity ? "Sem capacidade" : `${utilization.toFixed(0)}%`}</strong>
                    </div>
                    <div style={{ color: T.tertiary, fontFamily: T.mono, fontSize: 9, marginTop: 6 }}>{item.load_operator_min.toFixed(0)}/{item.capacity_operator_min.toFixed(0)}</div>
                    {item.peak_required !== undefined && (
                      <div style={{ color, fontFamily: T.mono, fontSize: 9, marginTop: 3 }}>
                        pico {item.peak_required}/{item.min_available ?? 0}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </Card>
        </>
      )}
    </div>
  );
}
