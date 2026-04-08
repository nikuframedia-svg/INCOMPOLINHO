import { useState, type CSSProperties, type ReactNode } from "react";
import { T } from "../../theme/tokens";

interface Props {
  children: ReactNode;
  style?: CSSProperties;
  onClick?: () => void;
  hoverable?: boolean;
}

export function Card({ children, style, onClick, hoverable = false }: Props) {
  const [hovered, setH] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => hoverable && setH(true)}
      onMouseLeave={() => hoverable && setH(false)}
      style={{
        background: hovered ? T.hover : T.card,
        borderRadius: T.radius,
        padding: 20,
        border: `1px solid ${hovered ? T.borderHover : T.border}`,
        transition: "all 0.2s ease",
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
