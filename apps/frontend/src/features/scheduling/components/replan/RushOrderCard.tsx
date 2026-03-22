/**
 * RushOrderCard — Rush/urgent order insertion panel.
 */
import { X, Zap } from 'lucide-react';
import { C } from '@/theme/color-bridge';
import { Card, Tag, toolColor } from '../atoms';
import type { RushOrderCardProps } from './types';

export function RushOrderCard({
  tools,
  focusIds,
  toolMap: TM,
  rushOrders,
  roTool,
  roQty,
  roDeadline,
  wdi,
  dates,
  dnames,
  setRoTool,
  setRoQty,
  setRoDeadline,
  addRushOrder,
  removeRushOrder,
}: RushOrderCardProps) {
  const labelStyle = {
    fontSize: 12,
    color: C.t4,
    marginBottom: 2,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '.04em',
  };

  const selectStyle = {
    padding: '4px 6px',
    borderRadius: 4,
    border: `1px solid ${C.bd}`,
    background: C.s2,
    color: C.t1,
    fontSize: 12,
    fontFamily: 'inherit',
  } as const;

  return (
    <Card style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: rushOrders.length > 0 ? 10 : 0,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
          <Zap
            size={12}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4, color: C.yl }}
          />
          Encomendas Urgentes {rushOrders.length > 0 && <Tag color={C.yl}>{rushOrders.length}</Tag>}
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'flex-end',
          marginBottom: rushOrders.length > 0 ? 10 : 0,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={labelStyle}>Ferramenta</div>
          <select
            value={roTool}
            onChange={(e) => setRoTool(e.target.value)}
            style={{ ...selectStyle, minWidth: 100 }}
          >
            <option value="">Selecionar...</option>
            {tools
              .filter(
                (t) =>
                  focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
              )
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.id}
                </option>
              ))}
          </select>
        </div>
        <div>
          <div style={labelStyle}>Qtd</div>
          <input
            type="number"
            value={roQty}
            onChange={(e) => setRoQty(Math.max(1, Number(e.target.value)))}
            style={{
              width: 70,
              padding: '4px 6px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: C.s2,
              color: C.t1,
              fontSize: 12,
              fontFamily: "'JetBrains Mono',monospace",
              textAlign: 'center',
            }}
          />
        </div>
        <div>
          <div style={labelStyle}>Deadline</div>
          <select
            value={roDeadline}
            onChange={(e) => setRoDeadline(Number(e.target.value))}
            style={selectStyle}
          >
            {wdi.map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={addRushOrder}
          disabled={!roTool}
          style={{
            padding: '5px 14px',
            borderRadius: 4,
            border: 'none',
            background: roTool ? C.yl : C.s3,
            color: roTool ? C.bg : C.t4,
            fontSize: 12,
            fontWeight: 600,
            cursor: roTool ? 'pointer' : 'default',
            fontFamily: 'inherit',
          }}
        >
          + Adicionar
        </button>
      </div>

      {rushOrders.map((ro, i) => {
        const tool = TM[ro.toolId];
        const hrs = tool ? ro.qty / tool.pH : 0;
        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 10px',
              background: `${C.yl}08`,
              borderRadius: 4,
              border: `1px solid ${C.yl}22`,
              borderLeft: `3px solid ${C.yl}`,
              marginBottom: 4,
            }}
          >
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: toolColor(tools, ro.toolId),
                fontFamily: "'JetBrains Mono',monospace",
              }}
            >
              {ro.toolId}
            </span>
            <span style={{ fontSize: 12, color: C.t2 }}>{ro.sku}</span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: C.t1,
                fontFamily: "'JetBrains Mono',monospace",
              }}
            >
              {ro.qty.toLocaleString()} pcs
            </span>
            <span style={{ fontSize: 12, color: C.t3 }}>{hrs.toFixed(1)}h</span>
            <span style={{ fontSize: 12, color: C.yl, fontWeight: 600 }}>
              até {dnames[ro.deadline]} {dates[ro.deadline]}
            </span>
            <span style={{ flex: 1 }} />
            <button
              onClick={() => removeRushOrder(i)}
              style={{
                background: 'none',
                border: 'none',
                color: C.t3,
                cursor: 'pointer',
                padding: '0 2px',
              }}
            >
              <X size={12} strokeWidth={2} />
            </button>
          </div>
        );
      })}

      {rushOrders.length === 0 && (
        <div style={{ fontSize: 12, color: C.t4, textAlign: 'center', padding: 8 }}>
          Sem encomendas urgentes
        </div>
      )}
    </Card>
  );
}
