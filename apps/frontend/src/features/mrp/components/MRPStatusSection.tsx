import { StatusBanner } from '@/components/Common/StatusBanner';
import type { MRPResult, MRPSkuViewResult } from '@/domain/types/scheduling';

interface MRPStatusSectionProps {
  mrp: MRPResult;
  skuView: MRPSkuViewResult;
}

export function MRPStatusSection({ mrp, skuView }: MRPStatusSectionProps) {
  const overloadedMachines = mrp.rccp.filter((e) => e.overloaded).length;
  const { skusWithStockout, skusWithBacklog } = skuView.summary;

  if (skusWithStockout > 5 || overloadedMachines > 3) {
    return (
      <StatusBanner
        variant="critical"
        message={`Risco — ${skusWithStockout} SKUs com stockout previsto, ${overloadedMachines} sobrecargas de máquina.`}
        details={skusWithBacklog > 0 ? `${skusWithBacklog} SKUs com backlog pendente.` : undefined}
      />
    );
  }

  if (skusWithStockout > 0 || overloadedMachines > 0 || skusWithBacklog > 0) {
    const parts: string[] = [];
    if (skusWithStockout > 0) parts.push(`${skusWithStockout} stockouts`);
    if (overloadedMachines > 0) parts.push(`${overloadedMachines} sobrecargas`);
    if (skusWithBacklog > 0) parts.push(`${skusWithBacklog} backlogs`);
    return <StatusBanner variant="warning" message={`Atenção — ${parts.join(', ')}.`} />;
  }

  return (
    <StatusBanner
      variant="ok"
      message="Todas as necessidades cobertas, sem sobrecargas detectadas."
    />
  );
}
