/**
 * StockSkuSidebar — SKU list with status badges for stock projection page.
 * Shows all SKUs sorted by urgency (stockout first).
 */

import { useMemo, useState } from 'react';
import { C } from '@/theme/color-bridge';
import { mono } from '../utils/mrp-helpers';
import type { SkuStatus, SkuSummary } from '../utils/stock-detail-compute';

const STATUS_COLOR: Record<SkuStatus, string> = {
  stockout: C.rd,
  low: C.yl,
  ok: C.ac,
  high: 'var(--semantic-blue)',
};

const STATUS_LABEL: Record<SkuStatus, string> = {
  stockout: 'Rutura',
  low: 'Stock baixo',
  ok: 'OK',
  high: 'Stock elevado',
};

interface StockSkuSidebarProps {
  summaries: SkuSummary[];
  selectedSku: string | undefined;
  onSelect: (sku: string) => void;
}

export function StockSkuSidebar({ summaries, selectedSku, onSelect }: StockSkuSidebarProps) {
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search) return summaries;
    const q = search.toLowerCase();
    return summaries.filter(
      (s) =>
        s.sku.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q) ||
        s.clients.some((c) => c.toLowerCase().includes(q)),
    );
  }, [summaries, search]);

  return (
    <div
      style={{
        width: 260,
        minWidth: 260,
        borderRight: `1px solid ${C.bd}`,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      <div style={{ padding: '12px 12px 8px' }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: C.t2,
            textTransform: 'uppercase',
            letterSpacing: '.04em',
            marginBottom: 8,
          }}
        >
          SKUs ({summaries.length})
        </div>
        <input
          type="text"
          placeholder="Pesquisar SKU..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: '100%',
            padding: '6px 8px',
            fontSize: 12,
            border: `1px solid ${C.bd}`,
            borderRadius: 4,
            background: 'var(--bg-card)',
            color: C.t1,
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0 4px 8px' }}>
        {filtered.map((s) => {
          const isActive = s.sku === selectedSku;
          const color = STATUS_COLOR[s.status];
          return (
            <button
              key={s.sku}
              onClick={() => onSelect(s.sku)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '8px',
                border: 'none',
                borderRadius: 4,
                background: isActive ? `${C.ac}15` : 'transparent',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: color,
                  flexShrink: 0,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: isActive ? C.ac : C.t1,
                    ...mono,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {s.sku}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: C.t3,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {s.name}
                </div>
              </div>
              <span style={{ fontSize: 12, color, fontWeight: 600, flexShrink: 0 }}>
                {s.status === 'stockout' ? `d${s.stockoutDay}` : STATUS_LABEL[s.status]}
              </span>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ padding: 16, textAlign: 'center', color: C.t3, fontSize: 12 }}>
            Sem resultados
          </div>
        )}
      </div>
    </div>
  );
}
