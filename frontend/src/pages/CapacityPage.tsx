import { CapacityView } from "../components/CapacityView";
import { T } from "../theme/tokens";

export function CapacityPage() {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div>
        <div style={{ color: T.primary, fontSize: 18, fontWeight: 700 }}>Carga e capacidade</div>
        <div style={{ color: T.secondary, fontSize: 12, marginTop: 3 }}>
          Confirma onde ainda existe tempo disponível e onde a carga ultrapassa a capacidade real.
        </div>
      </div>
      <CapacityView />
    </div>
  );
}
