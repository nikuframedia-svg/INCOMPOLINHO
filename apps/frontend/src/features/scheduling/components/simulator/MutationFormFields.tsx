/**
 * MutationFormFields — inline form for each mutation type's parameters.
 */

import type { EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';

interface Props {
  type: string;
  params: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
  engineData: EngineData;
}

const MACHINES = ['PRM019', 'PRM031', 'PRM039', 'PRM042', 'PRM043'] as const;
const LABOR_GROUPS = ['Grandes', 'Medias'] as const;
const DISPATCH_RULES = ['ATCS', 'EDD', 'CR', 'SPT', 'WSPT'] as const;

const inputStyle = {
  padding: '3px 6px',
  borderRadius: 4,
  border: `1px solid ${C.bd}`,
  background: C.bg,
  color: C.t1,
  fontSize: 12,
  fontFamily: 'inherit',
  minWidth: 80,
} as const;

function Lbl({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ fontSize: 11, color: C.t3, fontWeight: 500, minWidth: 60 }}>{children}</span>
  );
}

export function MutationFormFields({ type, params, onChange, engineData }: Props) {
  const set = (key: string, val: unknown) => onChange({ ...params, [key]: val });

  const machineSelect = (key: string, includeAll = false) => (
    <select
      style={inputStyle}
      value={String(params[key] ?? '')}
      onChange={(e) => set(key, e.target.value)}
    >
      {includeAll && <option value="__all__">Todas</option>}
      {MACHINES.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
    </select>
  );

  const daySelect = (key: string) => {
    const nDays = engineData.nDays || 80;
    return (
      <select
        style={inputStyle}
        value={Number(params[key] ?? 0)}
        onChange={(e) => set(key, Number(e.target.value))}
      >
        {Array.from({ length: nDays }, (_, i) => (
          <option key={i} value={i}>
            Dia {i}
            {engineData.dates?.[i] ? ` (${engineData.dates[i]})` : ''}
          </option>
        ))}
      </select>
    );
  };

  const skuSelect = (key: string) => {
    const skus = [...new Set((engineData.ops || []).map((o) => o.sku))].sort();
    return (
      <select
        style={{ ...inputStyle, minWidth: 140 }}
        value={String(params[key] ?? '')}
        onChange={(e) => set(key, e.target.value)}
      >
        <option value="">Seleccionar SKU...</option>
        {skus.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    );
  };

  const toolSelect = (key: string, includeAll = false) => {
    const tools = Object.keys(engineData.toolMap || {}).sort();
    return (
      <select
        style={{ ...inputStyle, minWidth: 120 }}
        value={String(params[key] ?? '')}
        onChange={(e) => set(key, e.target.value)}
      >
        {includeAll && <option value="__all__">Todas</option>}
        <option value="">Seleccionar...</option>
        {tools.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
    );
  };

  const row = { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const };

  switch (type) {
    case 'machine_down':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>Máquina</Lbl>
            {machineSelect('machine_id')}
          </div>
          <div style={row}>
            <Lbl>De dia</Lbl>
            {daySelect('start_day')}
            <Lbl>Até</Lbl>
            {daySelect('end_day')}
          </div>
          <div style={row}>
            <Lbl>Capacidade</Lbl>
            <select
              style={inputStyle}
              value={Number(params.capacity_factor ?? 0)}
              onChange={(e) => set('capacity_factor', Number(e.target.value))}
            >
              <option value={0}>0% (parada total)</option>
              <option value={0.25}>25%</option>
              <option value={0.5}>50%</option>
              <option value={0.75}>75%</option>
            </select>
          </div>
        </div>
      );
    case 'tool_down':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>Ferramenta</Lbl>
            {toolSelect('tool_id')}
          </div>
          <div style={row}>
            <Lbl>De dia</Lbl>
            {daySelect('start_day')}
            <Lbl>Até</Lbl>
            {daySelect('end_day')}
          </div>
        </div>
      );
    case 'operator_shortage':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>Grupo</Lbl>
            <select
              style={inputStyle}
              value={String(params.labor_group ?? 'Grandes')}
              onChange={(e) => set('labor_group', e.target.value)}
            >
              {LABOR_GROUPS.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </div>
          <div style={row}>
            <Lbl>Operadores</Lbl>
            <select
              style={inputStyle}
              value={Number(params.reduction ?? 1)}
              onChange={(e) => set('reduction', Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  -{n}
                </option>
              ))}
            </select>
          </div>
        </div>
      );
    case 'oee_change':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>Ferramenta</Lbl>
            {toolSelect('tool_id', true)}
          </div>
          <div style={row}>
            <Lbl>OEE</Lbl>
            <input
              type="range"
              min={30}
              max={90}
              step={5}
              value={Math.round(Number(params.new_oee ?? 0.66) * 100)}
              onChange={(e) => set('new_oee', Number(e.target.value) / 100)}
              style={{ width: 120 }}
            />
            <span style={{ fontSize: 12, color: C.t2, fontWeight: 600 }}>
              {Math.round(Number(params.new_oee ?? 0.66) * 100)}%
            </span>
          </div>
        </div>
      );
    case 'rush_order':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>SKU</Lbl>
            {skuSelect('sku')}
          </div>
          <div style={row}>
            <Lbl>Quantidade</Lbl>
            <input
              type="number"
              min={0}
              step={1000}
              value={Number(params.qty ?? 0)}
              onChange={(e) => set('qty', Number(e.target.value))}
              style={{ ...inputStyle, width: 100 }}
            />
          </div>
          <div style={row}>
            <Lbl>Até dia</Lbl>
            {daySelect('deadline_day')}
          </div>
        </div>
      );
    case 'demand_change':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>SKU</Lbl>
            {skuSelect('sku')}
          </div>
          <div style={row}>
            <Lbl>Factor</Lbl>
            <input
              type="range"
              min={50}
              max={200}
              step={10}
              value={Math.round(Number(params.factor ?? 1) * 100)}
              onChange={(e) => set('factor', Number(e.target.value) / 100)}
              style={{ width: 120 }}
            />
            <span style={{ fontSize: 12, color: C.t2, fontWeight: 600 }}>
              {Number(params.factor ?? 1).toFixed(1)}×
            </span>
          </div>
        </div>
      );
    case 'cancel_order':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>SKU</Lbl>
            {skuSelect('sku')}
          </div>
          <div style={row}>
            <Lbl>De dia</Lbl>
            {daySelect('from_day')}
            <Lbl>Até</Lbl>
            {daySelect('to_day')}
          </div>
        </div>
      );
    case 'third_shift':
      return (
        <div style={row}>
          <Lbl>Máquina</Lbl>
          {machineSelect('machine_id', true)}
        </div>
      );
    case 'overtime':
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>Máquina</Lbl>
            {machineSelect('machine_id', true)}
          </div>
          <div style={row}>
            <Lbl>Min extra/dia</Lbl>
            <select
              style={inputStyle}
              value={Number(params.extra_min ?? 120)}
              onChange={(e) => set('extra_min', Number(e.target.value))}
            >
              {[60, 90, 120, 180].map((n) => (
                <option key={n} value={n}>
                  {n} min
                </option>
              ))}
            </select>
          </div>
        </div>
      );
    case 'add_holiday':
      return (
        <div style={row}>
          <Lbl>Dia</Lbl>
          {daySelect('day_idx')}
        </div>
      );
    case 'remove_holiday':
      return (
        <div style={row}>
          <Lbl>Dia</Lbl>
          {daySelect('day_idx')}
        </div>
      );
    case 'force_move': {
      const ops = (engineData.ops || []).map((o) => o.id).sort();
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={row}>
            <Lbl>Operação</Lbl>
            <select
              style={{ ...inputStyle, minWidth: 140 }}
              value={String(params.op_id ?? '')}
              onChange={(e) => set('op_id', e.target.value)}
            >
              <option value="">Seleccionar...</option>
              {ops.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
          <div style={row}>
            <Lbl>Para</Lbl>
            {machineSelect('to_machine')}
          </div>
        </div>
      );
    }
    case 'change_dispatch_rule':
      return (
        <div style={row}>
          <Lbl>Regra</Lbl>
          <select
            style={inputStyle}
            value={String(params.rule ?? 'ATCS')}
            onChange={(e) => set('rule', e.target.value)}
          >
            {DISPATCH_RULES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      );
    default:
      return <div style={{ fontSize: 11, color: C.t3 }}>Tipo desconhecido: {type}</div>;
  }
}
