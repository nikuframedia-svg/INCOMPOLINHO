/**
 * RoutingsTab — Alternative routing table.
 *
 * Shows tool→machine routing with alternatives, speed coefficients,
 * and auto/manual toggle.
 */

import { Pencil } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { NikufraData } from '@/domain/nikufra-types';
import { useMasterDataStore } from '@/stores/useMasterDataStore';
import { EditableCell } from './EditableCell';
import './RoutingsTab.css';
import { C } from '@/theme/color-bridge';

interface RoutingsTabProps {
  data: NikufraData;
}

export function RoutingsTab({ data }: RoutingsTabProps) {
  const { tools, machines } = data;
  const routingOverrides = useMasterDataStore((s) => s.routingOverrides);
  const setRoutingOverride = useMasterDataStore((s) => s.setRoutingOverride);
  const toolOverrides = useMasterDataStore((s) => s.toolOverrides);
  const setToolOverride = useMasterDataStore((s) => s.setToolOverride);
  const [showAll, setShowAll] = useState(false);

  const machineOptions = useMemo(
    () => [{ value: '', label: '—' }, ...machines.map((m) => ({ value: m.id, label: m.id }))],
    [machines],
  );

  const enriched = useMemo(() => {
    return tools.map((t) => {
      const tov = toolOverrides[t.id];
      const rov = routingOverrides[t.id];
      const alt = tov?.alt ?? t.alt;
      const hasAlt = alt && alt !== '-' && alt !== '';
      const coeff = rov?.speedCoefficients?.[0] ?? 1.0;
      const useAuto = rov?.useAlternatives ?? true;
      return {
        ...t,
        alt: alt || '—',
        hasAlt: !!hasAlt,
        coeff,
        useAuto,
        hasOverride: !!tov?.alt || !!rov,
      };
    });
  }, [tools, toolOverrides, routingOverrides]);

  const withAlt = enriched.filter((t) => t.hasAlt);
  const withoutAlt = enriched.filter((t) => !t.hasAlt);
  const displayed = showAll ? enriched : withAlt;

  return (
    <div className="routings-tab">
      <div className="routings-tab__header">
        <span className="routings-tab__count">
          {withAlt.length} com alternativa · {withoutAlt.length} sem alternativa
        </span>
        <button className="routings-tab__toggle" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Só com alternativa' : 'Mostrar todas'}
        </button>
      </div>

      <table className="routings-tab__table">
        <thead>
          <tr>
            <th>SKU(s)</th>
            <th>Ferramenta</th>
            <th>Máq. Primária</th>
            <th>Alternativa</th>
            <th>Coef. Veloc.</th>
            <th>Auto</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {displayed.map((t) => (
            <tr key={t.id} className={t.hasAlt ? '' : 'routings-tab__no-alt'}>
              <td className="routings-tab__skus" title={t.skus.join(', ')}>
                {t.nm[0] || t.skus[0] || '—'}
              </td>
              <td className="routings-tab__tool">{t.id}</td>
              <td className="routings-tab__machine">{t.m}</td>
              <td>
                <EditableCell
                  value={t.alt}
                  type="select"
                  options={machineOptions}
                  isOverridden={toolOverrides[t.id]?.alt !== undefined}
                  onSave={(v) => {
                    const val = String(v) || '-';
                    setToolOverride(t.id, { alt: val });
                  }}
                />
              </td>
              <td>
                {t.hasAlt ? (
                  <EditableCell
                    value={t.coeff}
                    type="number"
                    isOverridden={routingOverrides[t.id]?.speedCoefficients !== undefined}
                    onSave={(v) => setRoutingOverride(t.id, { speedCoefficients: [Number(v)] })}
                  />
                ) : (
                  <span className="routings-tab__na">—</span>
                )}
              </td>
              <td>
                {t.hasAlt ? (
                  <button
                    className={`routings-tab__auto${t.useAuto ? ' routings-tab__auto--on' : ''}`}
                    onClick={() => setRoutingOverride(t.id, { useAlternatives: !t.useAuto })}
                  >
                    {t.useAuto ? 'AUTO' : 'MANUAL'}
                  </button>
                ) : (
                  <span className="routings-tab__na">—</span>
                )}
              </td>
              <td>{t.hasOverride && <Pencil size={10} style={{ color: C.ac, opacity: 0.7 }} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
