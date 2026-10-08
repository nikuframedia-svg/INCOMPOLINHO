import { useState } from "react";
import { T } from "../theme/tokens";
import { StockPage } from "./StockPage";
import { ExpeditionPage } from "./ExpeditionPage";

type DeliveryView = "reference" | "order";

const views: { id: DeliveryView; label: string; description: string }[] = [
  {
    id: "reference",
    label: "Por referência",
    description: "Stock projetado e risco de rutura por referência",
  },
  {
    id: "order",
    label: "Por encomenda",
    description: "Preparação das entregas por data e cliente",
  },
];

export function DeliveriesPage() {
  const [view, setView] = useState<DeliveryView>("reference");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        className="deliveries-view-tabs"
        role="tablist"
        aria-label="Perspetiva das entregas"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(220px, 1fr))",
          gap: 8,
          maxWidth: 720,
        }}
      >
        {views.map((item) => {
          const active = item.id === view;
          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={active}
              onClick={() => setView(item.id)}
              style={{
                background: active ? T.card : "transparent",
                border: `1px solid ${active ? T.borderHover : T.border}`,
                borderLeft: `3px solid ${active ? T.blue : "transparent"}`,
                borderRadius: 8,
                padding: "10px 12px",
                textAlign: "left",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              <span style={{ display: "block", color: T.primary, fontSize: 12, fontWeight: 600 }}>
                {item.label}
              </span>
              <span style={{ display: "block", color: T.tertiary, fontSize: 10, marginTop: 3 }}>
                {item.description}
              </span>
            </button>
          );
        })}
      </div>

      <div role="tabpanel">{view === "reference" ? <StockPage /> : <ExpeditionPage />}</div>
    </div>
  );
}
