/**
 * CoverageTimeline — Horizontal bar chart of stock coverage by SKU.
 * Sorted ascending (least coverage first). Clickable → StockDetailPage.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { C } from '@/theme/color-bridge';
import { fmtQty, mono } from '../utils/mrp-helpers';
import type { StockRow } from '../utils/stock-compute';
import { coverageColor } from '../utils/stock-compute';

const MAX_DAYS = 80;
const VISIBLE_ROWS = 20;

interface CoverageTimelineProps {
  rows: StockRow[];
}

export function CoverageTimeline({ rows }: CoverageTimelineProps) {
  const navigate = useNavigate();
  const [hovIdx, setHovIdx] = useState<number | null>(null);

  const sorted = [...rows].sort((a, b) => a.coverageDays - b.coverageDays);
  const visible = sorted.slice(0, VISIBLE_ROWS);

  return (
    <div className="mrp__card" style={{ padding: 12 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.t2,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
          marginBottom: 8,
        }}
      >
        Cobertura por SKU (dias)
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
          maxHeight: 420,
          overflowY: 'auto',
        }}
      >
        {visible.map((row, i) => {
          const pct = Math.min((row.coverageDays / MAX_DAYS) * 100, 100);
          const color = coverageColor(row.coverageDays, row.stockoutDay);
          const isHov = hovIdx === i;

          return (
            <div
              key={`${row.sku}-${row.toolCode}`}
              className="mrp__cov-row"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                position: 'relative',
              }}
              onClick={() => navigate(`/mrp/stock/${encodeURIComponent(row.sku)}`)}
              onMouseEnter={() => setHovIdx(i)}
              onMouseLeave={() => setHovIdx(null)}
            >
              <span
                style={{
                  width: 80,
                  minWidth: 80,
                  fontSize: 12,
                  color: C.t2,
                  ...mono,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {row.sku}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 16,
                  background: `${C.t4}22`,
                  borderRadius: 3,
                  position: 'relative',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${Math.max(pct, 2)}%`,
                    background: color,
                    borderRadius: 3,
                    opacity: isHov ? 1 : 0.85,
                    transition: 'opacity 0.1s',
                  }}
                />
              </div>
              <span
                style={{
                  width: 36,
                  minWidth: 36,
                  fontSize: 12,
                  color,
                  fontWeight: 600,
                  textAlign: 'right',
                  ...mono,
                }}
              >
                {row.coverageDays > 0 ? `${row.coverageDays}d` : '0d'}
              </span>
              {isHov && (
                <div
                  style={{
                    position: 'absolute',
                    bottom: 'calc(100% + 4px)',
                    left: 90,
                    background: C.s3,
                    border: `1px solid ${C.bd}`,
                    borderRadius: 6,
                    padding: '6px 10px',
                    zIndex: 20,
                    width: 200,
                    pointerEvents: 'none',
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{row.sku}</div>
                  <div style={{ fontSize: 12, color: C.t3, marginBottom: 4 }}>{row.name}</div>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 1fr',
                      gap: 2,
                      fontSize: 12,
                    }}
                  >
                    <span style={{ color: C.t3 }}>Cobertura</span>
                    <span style={{ color, fontWeight: 600 }}>{row.coverageDays} dias</span>
                    <span style={{ color: C.t3 }}>Stock</span>
                    <span style={{ color: C.t1, fontWeight: 600 }}>{fmtQty(row.currentStock)}</span>
                    <span style={{ color: C.t3 }}>Máquina</span>
                    <span style={{ color: C.t2 }}>{row.machine}</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {sorted.length > VISIBLE_ROWS && (
        <div style={{ fontSize: 12, color: C.t3, textAlign: 'center', marginTop: 6 }}>
          +{sorted.length - VISIBLE_ROWS} SKUs não mostrados
        </div>
      )}
    </div>
  );
}
