/**
 * SkuDetailWidget — compact SKU reference card.
 */

export function SkuDetailWidget({ data }: { data: Record<string, unknown> }) {
  const sku = (data.sku ?? '?') as string;
  const allFields: [string, unknown][] = [
    ['Designação', data.designação],
    ['Máquina', data.máquina],
    ['Ferramenta', data.ferramenta],
    ['Peças/hora', data['peças/hora']],
    ['Stock', data.stock],
    ['Atraso', data.atraso],
    ['Gémea', data.gémea],
    ['Encomendas', data.encomendas],
    ['Procura total', data.procura_total],
  ];
  const fields = allFields.filter((f): f is [string, unknown] => f[1] != null && f[1] !== '' && f[1] !== 0);

  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--accent)',
          fontFamily: "'JetBrains Mono',monospace",
          marginBottom: 4,
        }}
      >
        {sku}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', gap: '2px 8px' }}>
        {fields.map(([label, value]) => (
          <div key={label} style={{ display: 'contents' }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</span>
            <span style={{ fontSize: 10, color: 'var(--text-primary)' }}>
              {typeof value === 'number' ? value.toLocaleString('pt-PT') : String(value)}
            </span>
          </div>
        ))}
      </div>
      {data.clientes != null && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
          Clientes: {Array.isArray(data.clientes) ? (data.clientes as string[]).join(', ') : String(data.clientes)}
        </div>
      )}
    </div>
  );
}
