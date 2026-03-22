/**
 * ToolsTab — Editable table of factory tools (ferramentas).
 *
 * Shows tool ID, primary machine, alternative, setup, pH, operators, SKUs.
 * Filterable by machine and text search.
 */

import { Pencil } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { NikufraData } from '@/domain/nikufra-types';
import { useMasterDataStore } from '@/stores/useMasterDataStore';
import { EditableCell } from './EditableCell';
import './ToolsTab.css';
import { C } from '@/theme/color-bridge';

interface ToolsTabProps {
  data: NikufraData;
}

export function ToolsTab({ data }: ToolsTabProps) {
  const { tools, machines } = data;
  const overrides = useMasterDataStore((s) => s.toolOverrides);
  const setOverride = useMasterDataStore((s) => s.setToolOverride);
  const [machineFilter, setMachineFilter] = useState('all');
  const [search, setSearch] = useState('');

  const machineOptions = useMemo(
    () => [{ value: '', label: '—' }, ...machines.map((m) => ({ value: m.id, label: m.id }))],
    [machines],
  );

  const filtered = useMemo(() => {
    const lc = search.toLowerCase();
    return tools
      .map((t) => {
        const ov = overrides[t.id];
        return {
          ...t,
          m: ov?.m ?? t.m,
          alt: ov?.alt ?? t.alt,
          s: ov?.s ?? t.s,
          pH: ov?.pH ?? t.pH,
          op: ov?.op ?? t.op,
          hasOverride: !!ov,
        };
      })
      .filter((t) => {
        if (machineFilter !== 'all' && t.m !== machineFilter && t.alt !== machineFilter)
          return false;
        if (
          lc &&
          !t.id.toLowerCase().includes(lc) &&
          !t.skus.some((s) => s.toLowerCase().includes(lc))
        )
          return false;
        return true;
      });
  }, [tools, overrides, machineFilter, search]);

  return (
    <div className="tools-tab">
      <div className="tools-tab__filters">
        <select
          className="tools-tab__select"
          value={machineFilter}
          onChange={(e) => setMachineFilter(e.target.value)}
        >
          <option value="all">Todas máquinas ({tools.length})</option>
          {machines.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}
            </option>
          ))}
        </select>
        <input
          className="tools-tab__search"
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar ferramenta ou SKU..."
        />
        <span className="tools-tab__count">{filtered.length} ferramentas</span>
      </div>

      <table className="tools-tab__table">
        <thead>
          <tr>
            <th>Ferramenta</th>
            <th>Máq. Primária</th>
            <th>Alternativa</th>
            <th>Setup (h)</th>
            <th>Peças/H</th>
            <th>Ops</th>
            <th>SKUs</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((t) => (
            <tr key={t.id}>
              <td className="tools-tab__id">{t.id}</td>
              <td>
                <EditableCell
                  value={t.m}
                  type="select"
                  options={machineOptions.filter((o) => o.value !== '')}
                  isOverridden={overrides[t.id]?.m !== undefined}
                  onSave={(v) => setOverride(t.id, { m: String(v) })}
                />
              </td>
              <td>
                <EditableCell
                  value={t.alt || '—'}
                  type="select"
                  options={machineOptions}
                  isOverridden={overrides[t.id]?.alt !== undefined}
                  onSave={(v) => setOverride(t.id, { alt: String(v) || '-' })}
                />
              </td>
              <td>
                <EditableCell
                  value={t.s}
                  type="number"
                  isOverridden={overrides[t.id]?.s !== undefined}
                  onSave={(v) => setOverride(t.id, { s: Number(v) })}
                />
              </td>
              <td>
                <EditableCell
                  value={t.pH}
                  type="number"
                  isOverridden={overrides[t.id]?.pH !== undefined}
                  onSave={(v) => setOverride(t.id, { pH: Number(v) })}
                />
              </td>
              <td>
                <EditableCell
                  value={t.op}
                  type="number"
                  isOverridden={overrides[t.id]?.op !== undefined}
                  onSave={(v) => setOverride(t.id, { op: Number(v) })}
                />
              </td>
              <td className="tools-tab__skus" title={t.skus.join(', ')}>
                {t.skus.length}
              </td>
              <td>{t.hasOverride && <Pencil size={10} style={{ color: C.ac, opacity: 0.7 }} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
