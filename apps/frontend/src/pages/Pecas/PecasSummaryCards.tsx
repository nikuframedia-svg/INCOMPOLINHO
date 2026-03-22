import { C } from '@/theme/color-bridge';

interface SCardProps {
  label: string;
  value: string;
  color: string;
}

export function SCard({ label, value, color }: SCardProps) {
  return (
    <div className="pec__scard" style={{ borderLeft: `3px solid ${color}` }}>
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.t3,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
        }}
      >
        {label}
      </span>
      <span
        style={{ fontSize: 20, fontWeight: 700, color, fontFamily: "'JetBrains Mono',monospace" }}
      >
        {value}
      </span>
    </div>
  );
}

interface PecasSummaryCardsProps {
  totalSKUs: number;
  totalDemand: number;
  totalStock: number;
  totalBacklog: number;
}

export function PecasSummaryCards({
  totalSKUs,
  totalDemand,
  totalStock,
  totalBacklog,
}: PecasSummaryCardsProps) {
  return (
    <div className="pec__summary">
      <SCard label="SKUs" value={String(totalSKUs)} color={C.ac} />
      <SCard
        label="Demand 8d"
        value={totalDemand > 1000 ? `${(totalDemand / 1000).toFixed(0)}K` : String(totalDemand)}
        color={C.bl}
      />
      <SCard
        label="Stock Total"
        value={totalStock > 1000 ? `${(totalStock / 1000).toFixed(0)}K` : String(totalStock)}
        color={C.ac}
      />
      <SCard
        label="Backlog Total"
        value={totalBacklog > 1000 ? `${(totalBacklog / 1000).toFixed(0)}K` : String(totalBacklog)}
        color={totalBacklog > 0 ? C.yl : C.ac}
      />
    </div>
  );
}
