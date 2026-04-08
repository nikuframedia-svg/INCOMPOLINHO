/** Clean beige palette — high contrast, warm neutrals */
export const T = {
  // Backgrounds (claro → escuro)
  bg: "#FAF8F4",          // página principal — bege claro
  card: "#FFFFFF",         // cards — branco puro (contraste máximo)
  elevated: "#EFEBE3",     // superfícies elevadas — bege médio
  hover: "#E8E2D8",        // hover state
  sidebar: "#F5F0E8",      // sidebar — bege quente

  // Bordas — visíveis, não subtis
  border: "#D6CFC2",
  borderHover: "#B8AFA2",

  // Texto — alto contraste sobre beige
  primary: "#1A1714",      // quase preto
  secondary: "#5C554C",    // cinza-castanho escuro
  tertiary: "#8A8078",     // cinza-castanho médio

  // Cores semânticas — saturadas para contrastar com beige
  blue: "#2563EB",
  green: "#1B7A3D",
  orange: "#CA860C",
  red: "#C2410C",
  purple: "#7C3AED",
  yellow: "#A16207",
  teal: "#0E7490",

  // Layout
  radius: 14,
  radiusSm: 10,

  // Typography
  mono: "ui-monospace,'SF Mono','Menlo','Consolas',monospace",
  sans: "-apple-system,'SF Pro Display','SF Pro Text','Helvetica Neue',sans-serif",
} as const;

/** Tool-id to color — saturated for beige background */
const TOOL_COLORS = [
  "#2563EB", "#1B7A3D", "#CA860C", "#C2410C", "#7C3AED",
  "#0E7490", "#DB2777", "#A16207", "#92400E", "#4F46E5",
];

export function toolColor(toolId: string): string {
  const n = parseInt(toolId.replace(/\D/g, ""), 10) || 0;
  return TOOL_COLORS[n % TOOL_COLORS.length];
}
