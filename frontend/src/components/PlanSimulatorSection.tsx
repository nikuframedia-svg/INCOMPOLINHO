import { useDataStore } from "../stores/useDataStore";
import { T } from "../theme/tokens";
import { MachineDowntimeQuickAction } from "./MachineDowntimeQuickAction";
import { RobustnessPanel } from "./RobustnessPanel";
import { SimulatorPanel } from "../pages/SimulatorPage";

interface PlanSimulatorSectionProps {
  currentDay: number;
  workdays: string[];
  open: boolean;
  onToggle: () => void;
  onApplied: (range?: [number, number]) => void;
}

export function PlanSimulatorSection({
  currentDay,
  workdays,
  open,
  onToggle,
  onApplied,
}: PlanSimulatorSectionProps) {
  const activeMutations = useDataStore((state) => state.activeMutations);

  return (
    <section
      style={{
        border: `1px solid ${open ? `${T.orange}66` : T.border}`,
        borderRadius: T.radius,
        background: T.card,
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls="plan-simulator-content"
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "13px 16px",
          border: 0,
          borderLeft: `4px solid ${T.orange}`,
          background: open ? `${T.orange}0D` : T.card,
          color: T.primary,
          cursor: "pointer",
          fontFamily: "inherit",
          textAlign: "left",
        }}
      >
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", fontSize: 13, fontWeight: 700 }}>Simular alterações</span>
          <span style={{ display: "block", color: T.secondary, fontSize: 10, marginTop: 2 }}>
            Paragens, capacidade e compromissos de entrega
          </span>
        </span>
        {activeMutations.length > 0 && (
          <span
            style={{
              padding: "3px 7px",
              borderRadius: 999,
              background: `${T.orange}18`,
              color: T.orange,
              fontFamily: T.mono,
              fontSize: 10,
              fontWeight: 700,
            }}
          >
            {activeMutations.length} ativa{activeMutations.length === 1 ? "" : "s"}
          </span>
        )}
        <span aria-hidden="true" style={{ color: T.orange, fontSize: 16 }}>{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div
          id="plan-simulator-content"
          style={{ display: "grid", gap: 14, padding: 16, borderTop: `1px solid ${T.border}` }}
        >
          <MachineDowntimeQuickAction
            currentDay={currentDay}
            workdays={workdays}
            onApplied={onApplied}
          />

          <RobustnessPanel />

          <details
            style={{
              border: `1px solid ${T.border}`,
              borderRadius: T.radiusSm,
              background: T.bg,
              overflow: "hidden",
            }}
          >
            <summary
              style={{
                padding: "11px 14px",
                color: T.secondary,
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 650,
              }}
            >
              Outras simulações e promessas
            </summary>
            <div style={{ padding: 14, borderTop: `1px solid ${T.border}` }}>
              <SimulatorPanel onApplied={() => onApplied()} />
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
