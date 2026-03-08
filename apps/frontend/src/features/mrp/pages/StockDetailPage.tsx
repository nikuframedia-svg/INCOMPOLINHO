import { useParams } from 'react-router-dom';
import { StubPage } from '@/components/Common/StubPage';

export function StockDetailPage() {
  const { sku } = useParams<{ sku: string }>();
  return (
    <StubPage
      title={`Stock — ${sku ?? 'SKU'}`}
      description="Detalhe de stock por SKU em desenvolvimento."
    />
  );
}
