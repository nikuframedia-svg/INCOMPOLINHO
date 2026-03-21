/**
 * ClientGroup — Collapsible client group for EncomendasTab client view.
 */

import { ChevronDown, ChevronRight } from 'lucide-react';
import { C } from '@/lib/engine';
import type { ClientRiskGroup } from '../utils/encomendas-compute';
import { fmtQty, mono } from '../utils/mrp-helpers';
import { OrderRow } from './OrderRow';

export function ClientGroup({
  group,
  expanded,
  onToggle,
  numDays,
  dates,
  dnames,
}: {
  group: ClientRiskGroup;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  numDays: number;
  dates: string[];
  dnames: string[];
}) {
  const clientKey = `__client__${group.customerCode}`;
  const isExpanded = expanded.has(clientKey);

  return (
    <div style={{ marginBottom: 4 }}>
      <div
        className="mrp__enc-client-row"
        onClick={() => onToggle(clientKey)}
        style={{ cursor: 'pointer' }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
          <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{group.customerName}</span>
          <span style={{ fontSize: 12, color: C.t3, ...mono }}>{group.customerCode}</span>
        </span>
        <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: C.t2 }}>{group.totalOrders} encomendas</span>
          {group.criticalCount > 0 && (
            <span style={{ fontSize: 12, color: C.rd, fontWeight: 600 }}>
              {group.criticalCount} criticas
            </span>
          )}
          {group.warningCount > 0 && (
            <span style={{ fontSize: 12, color: C.yl }}>{group.warningCount} em risco</span>
          )}
          {group.totalShortfall > 0 && (
            <span style={{ ...mono, fontSize: 12, color: C.rd }}>
              Deficit: {fmtQty(group.totalShortfall)}
            </span>
          )}
        </span>
      </div>

      {isExpanded && (
        <table className="mrp__table" style={{ marginTop: 4, marginBottom: 8 }}>
          <thead>
            <tr>
              <th style={{ width: 20 }} />
              <th style={{ width: 20 }} />
              <th>SKU</th>
              <th>Produto</th>
              <th style={{ textAlign: 'right' }}>Deficit</th>
              <th style={{ textAlign: 'right' }}>Cobertura</th>
              <th>Produção</th>
            </tr>
          </thead>
          <tbody>
            {group.entries.map((entry) => (
              <OrderRow
                key={entry.opId}
                entry={entry}
                isExpanded={expanded.has(entry.opId)}
                onToggle={() => onToggle(entry.opId)}
                numDays={numDays}
                dates={dates}
                dnames={dnames}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
