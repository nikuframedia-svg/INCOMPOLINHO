import { useMemo, useState } from "react";
import { T } from "../../theme/tokens";
import { EmptyState } from "./EmptyState";

export interface DataColumn<Row> {
  id: string;
  label: string;
  value: (row: Row) => string | number | null | undefined;
  render?: (row: Row) => React.ReactNode;
  sortable?: boolean;
  width?: number | string;
  help?: string;
}

export function DataTable<Row>({
  rows,
  columns,
  rowKey,
  searchPlaceholder = "Pesquisar nesta lista…",
  emptyTitle = "Sem resultados",
  emptyDetail = "Altera a pesquisa ou os filtros para voltar a ver resultados.",
  maxHeight = 600,
  onRowClick,
  initialSort,
  toolbar,
}: {
  rows: Row[];
  columns: DataColumn<Row>[];
  rowKey: (row: Row) => string;
  searchPlaceholder?: string;
  emptyTitle?: string;
  emptyDetail?: string;
  maxHeight?: number;
  onRowClick?: (row: Row) => void;
  initialSort?: { id: string; direction: "asc" | "desc" };
  toolbar?: React.ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState(initialSort ?? { id: columns[0]?.id ?? "", direction: "asc" as const });
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("pt-PT");
    const filtered = normalized
      ? rows.filter((row) => columns.some((column) => String(column.value(row) ?? "").toLocaleLowerCase("pt-PT").includes(normalized)))
      : rows;
    const column = columns.find((candidate) => candidate.id === sort.id);
    if (!column || column.sortable === false) return filtered;
    return [...filtered].sort((left, right) => {
      const a = column.value(left);
      const b = column.value(right);
      const result = typeof a === "number" && typeof b === "number"
        ? a - b
        : String(a ?? "").localeCompare(String(b ?? ""), "pt-PT", { numeric: true, sensitivity: "base" });
      return sort.direction === "asc" ? result : -result;
    });
  }, [columns, query, rows, sort]);

  const changeSort = (column: DataColumn<Row>) => {
    if (column.sortable === false) return;
    setSort((current) => current.id === column.id
      ? { id: column.id, direction: current.direction === "asc" ? "desc" : "asc" }
      : { id: column.id, direction: "asc" });
  };

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          style={{
            width: 270,
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            background: T.card,
            color: T.primary,
            padding: "7px 10px",
            fontSize: 11,
          }}
        />
        {toolbar}
        <span style={{ marginLeft: "auto", color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
          {visible.length} de {rows.length}
        </span>
      </div>
      <div style={{ overflow: "auto", maxHeight, border: `1px solid ${T.border}`, borderRadius: 10, background: T.card }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 680 }}>
          <thead style={{ position: "sticky", top: 0, zIndex: 2, background: T.elevated }}>
            <tr>
              {columns.map((column) => {
                const active = sort.id === column.id;
                return (
                  <th
                    key={column.id}
                    scope="col"
                    title={column.help}
                    style={{
                      width: column.width,
                      padding: "9px 11px",
                      borderBottom: `1px solid ${T.border}`,
                      textAlign: "left",
                      color: active ? T.primary : T.secondary,
                      fontSize: 10,
                      fontWeight: 700,
                      whiteSpace: "nowrap",
                    }}
                  >
                    <button
                      type="button"
                      disabled={column.sortable === false}
                      onClick={() => changeSort(column)}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        border: 0,
                        padding: 0,
                        background: "transparent",
                        color: "inherit",
                        cursor: column.sortable === false ? "default" : "pointer",
                        font: "inherit",
                      }}
                    >
                      {column.label}
                      {column.sortable !== false && <span aria-hidden="true">{active ? (sort.direction === "asc" ? "↑" : "↓") : "↕"}</span>}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr
                key={rowKey(row)}
                className="pp-table-row"
                tabIndex={onRowClick ? 0 : undefined}
                onClick={() => onRowClick?.(row)}
                onKeyDown={(event) => {
                  if (onRowClick && (event.key === "Enter" || event.key === " ")) onRowClick(row);
                }}
                style={{
                  borderBottom: `1px solid ${T.border}`,
                  cursor: onRowClick ? "pointer" : undefined,
                }}
              >
                {columns.map((column) => (
                  <td key={column.id} style={{ padding: "8px 11px", color: T.secondary, fontSize: 11, verticalAlign: "top" }}>
                    {column.render ? column.render(row) : String(column.value(row) ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && <EmptyState title={emptyTitle} detail={emptyDetail} />}
      </div>
    </div>
  );
}
