import { T } from "../../theme/tokens";

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div style={{ padding: "32px 20px", textAlign: "center" }}>
      <div style={{ color: T.primary, fontSize: 13, fontWeight: 650 }}>{title}</div>
      {detail && <div style={{ color: T.tertiary, fontSize: 11, marginTop: 5 }}>{detail}</div>}
    </div>
  );
}
