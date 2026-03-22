/**
 * MachinesTab — Editable table of factory machines.
 *
 * Shows machine ID, area, status, capacity, tool count, SKU count.
 * Expandable rows show compatible tools and produced SKUs.
 */

import { ChevronDown, ChevronRight, Pencil } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { NikufraData } from '@/domain/nikufra-types';
import { useMasterDataStore } from '@/stores/useMasterDataStore';
import { EditableCell } from './EditableCell';
import './MachinesTab.css';
import { C } from '@/theme/color-bridge';

interface MachinesTabProps {
  data: NikufraData;
}

export function MachinesTab({ data }: MachinesTabProps) {
  const { machines, tools, operations } = data;
  const overrides = useMasterDataStore((s) => s.machineOverrides);
  const setOverride = useMasterDataStore((s) => s.setMachineOverride);
  const [expanded, setExpanded] = useState<string | null>(null);

  const enriched = useMemo(() => {
    return machines.map((m) => {
      const ov = overrides[m.id];
      const toolCount = tools.filter((t) => t.m === m.id || t.alt === m.id).length;
      const skuCount = new Set(operations.filter((o) => o.m === m.id).map((o) => o.sku)).size;
      const compatTools = tools.filter((t) => t.m === m.id || t.alt === m.id);
      const skus = operations.filter((o) => o.m === m.id);
      return {
        ...m,
        area: ov?.area ?? m.area,
        status: ov?.status ?? m.status ?? 'running',
        capacityPerDay: ov?.capacityPerDay ?? 1020,
        toolCount,
        skuCount,
        compatTools,
        skus,
        hasOverride: !!ov,
      };
    });
  }, [machines, tools, operations, overrides]);

  return (
    <div className="machines-tab">
      <div className="machines-tab__header">
        <span className="machines-tab__count">{machines.length} máquinas</span>
      </div>

      <table className="machines-tab__table">
        <thead>
          <tr>
            <th></th>
            <th>Máquina</th>
            <th>Área</th>
            <th>Estado</th>
            <th>Cap/Dia (min)</th>
            <th>Ferramentas</th>
            <th>SKUs</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {enriched.map((m) => {
            const isExp = expanded === m.id;
            return (
              <tr key={m.id} className="machines-tab__group">
                <td
                  className="machines-tab__expand"
                  onClick={() => setExpanded(isExp ? null : m.id)}
                >
                  {isExp ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </td>
                <td className="machines-tab__id">{m.id}</td>
                <td>
                  <span
                    className="machines-tab__area"
                    style={{
                      background: m.area === 'PG1' ? `${C.bl}18` : `${C.pp}18`,
                      color: m.area === 'PG1' ? C.bl : C.pp,
                    }}
                  >
                    {m.area}
                  </span>
                </td>
                <td>
                  <span className="machines-tab__status">
                    <span
                      className="machines-tab__dot"
                      style={{ background: m.status === 'running' ? C.ac : C.rd }}
                    />
                    {m.status === 'running' ? 'RUN' : 'DOWN'}
                  </span>
                </td>
                <td>
                  <EditableCell
                    value={m.capacityPerDay}
                    type="number"
                    isOverridden={overrides[m.id]?.capacityPerDay !== undefined}
                    onSave={(v) => setOverride(m.id, { capacityPerDay: Number(v) })}
                  />
                </td>
                <td className="machines-tab__num">{m.toolCount}</td>
                <td className="machines-tab__num">{m.skuCount}</td>
                <td>
                  {m.hasOverride && <Pencil size={10} style={{ color: C.ac, opacity: 0.7 }} />}
                </td>
                {isExp && (
                  <td colSpan={8} className="machines-tab__detail">
                    <div className="machines-tab__detail-section">
                      <div className="machines-tab__detail-title">
                        Ferramentas compatíveis ({m.compatTools.length})
                      </div>
                      <div className="machines-tab__detail-list">
                        {m.compatTools.map((t) => (
                          <span key={t.id} className="machines-tab__detail-item">
                            {t.id}
                            {t.m !== m.id && (
                              <span className="machines-tab__detail-alt">(alt)</span>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="machines-tab__detail-section">
                      <div className="machines-tab__detail-title">
                        SKUs produzidos ({m.skus.length})
                      </div>
                      <div className="machines-tab__detail-list">
                        {m.skus.slice(0, 20).map((o) => (
                          <span key={o.id} className="machines-tab__detail-item">
                            {o.sku} — {o.nm}
                          </span>
                        ))}
                        {m.skus.length > 20 && (
                          <span className="machines-tab__detail-more">
                            +{m.skus.length - 20} mais
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
