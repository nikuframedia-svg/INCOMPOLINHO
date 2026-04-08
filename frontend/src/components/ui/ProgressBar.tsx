import { T } from "../../theme/tokens";

interface Props {
  value: number;
  color?: string;
  height?: number;
  bg?: string;
}

export function ProgressBar({ value, color = T.blue, height = 4, bg = "#E8E2D8" }: Props) {
  return (
    <div style={{ width: "100%", height, borderRadius: height, background: bg, overflow: "hidden" }}>
      <div
        style={{
          width: `${Math.min(value, 100)}%`,
          height: "100%",
          borderRadius: height,
          background: color,
          transition: "width 0.5s ease",
        }}
      />
    </div>
  );
}
