/**
 * ProductsTab — Table of all products (SKU/operations).
 *
 * Shows SKU, name, machine, tool, pH, twin, client.
 * Filterable by machine, client, and text search.
 */

import { Pencil } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { NikufraData } from '@/domain/nikufra-types';
import { useMasterDataStore } from '@/stores/useMasterDataStore';
import { EditableCell } from './EditableCell';
import './ProductsTab.css';
import { C } from '@/theme/color-bridge';

interface ProductsTabProps {
  data: NikufraData;
}

export function ProductsTab({ data }: ProductsTabProps) {
  const { operations, machines, customers } = data;
  const overrides = useMasterDataStore((s) => s.productOverrides);
  const setOverride = useMasterDataStore((s) => s.setProductOverride);
  const [machineFilter, setMachineFilter] = useState('all');
  const [clientFilter, setClientFilter] = useState('all');
  const [search, setSearch] = useState('');

  const uniqueClients = useMemo(() => {
    if (customers && customers.length > 0) {
      return customers.map((c) => ({ id: c.code, nm: c.name }));
    }
    const map = new Map<string, string>();
    for (const o of operations) {
      if (o.cl && !map.has(o.cl)) map.set(o.cl, o.clNm || o.cl);
    }
    return Array.from(map, ([id, nm]) => ({ id, nm }));
  }, [operations, customers]);

  const twinCount = useMemo(
    () => operations.filter((o) => o.twin && o.twin !== '-').length,
    [operations],
  );

  const filtered = useMemo(() => {
    const lc = search.toLowerCase();
    return operations
      .map((o) => {
        const ov = overrides[o.id];
        return {
          ...o,
          pH: ov?.pH ?? o.pH,
          twin: ov?.twin ?? o.twin,
          hasOverride: !!ov,
        };
      })
      .filter((o) => {
        if (machineFilter !== 'all' && o.m !== machineFilter) return false;
        if (clientFilter !== 'all' && o.cl !== clientFilter) return false;
        if (lc && !o.sku.toLowerCase().includes(lc) && !o.nm.toLowerCase().includes(lc))
          return false;
        return true;
      });
  }, [operations, overrides, machineFilter, clientFilter, search]);

  return (
    <div className="products-tab">
      <div className="products-tab__filters">
        <select
          className="products-tab__select"
          value={machineFilter}
          onChange={(e) => setMachineFilter(e.target.value)}
        >
          <option value="all">Todas máquinas</option>
          {machines.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}
            </option>
          ))}
        </select>
        <select
          className="products-tab__select"
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
        >
          <option value="all">Todos clientes</option>
          {uniqueClients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nm || c.id}
            </option>
          ))}
        </select>
        <input
          className="products-tab__search"
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar SKU ou designação..."
        />
        <span className="products-tab__count">
          {filtered.length} produtos · {uniqueClients.length} clientes · {twinCount} gémeas
        </span>
      </div>

      <div className="products-tab__scroll">
        <table className="products-tab__table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Designação</th>
              <th>Máquina</th>
              <th>Ferramenta</th>
              <th>Peças/H</th>
              <th>Gémea</th>
              <th>Cliente</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((o) => (
              <tr key={o.id}>
                <td className="products-tab__sku">{o.sku}</td>
                <td className="products-tab__nm">{o.nm}</td>
                <td className="products-tab__mono">{o.m}</td>
                <td className="products-tab__mono">{o.t}</td>
                <td>
                  <EditableCell
                    value={o.pH}
                    type="number"
                    isOverridden={overrides[o.id]?.pH !== undefined}
                    onSave={(v) => setOverride(o.id, { pH: Number(v) })}
                  />
                </td>
                <td className="products-tab__twin">{o.twin && o.twin !== '-' ? o.twin : '—'}</td>
                <td className="products-tab__client">{o.clNm || o.cl || '—'}</td>
                <td>
                  {o.hasOverride && <Pencil size={10} style={{ color: C.ac, opacity: 0.7 }} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
