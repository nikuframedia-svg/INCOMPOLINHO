/**
 * DayRangePicker — Selector de intervalo de dias para downtime.
 */
import { X } from 'lucide-react';
import { C } from '../../../../lib/engine';
import type { DayRangePickerProps } from './types';

export function DayRangePicker({
  editingDown,
  currentDown,
  dates,
  dnames,
  wdi,
  downStartDay,
  downEndDay,
  setDownStartDay,
  setDownEndDay,
  setEditingDown,
  setResourceDown,
  clearResourceDown,
}: DayRangePickerProps) {
  const selectStyle = {
    padding: '3px 6px',
    borderRadius: 4,
    border: `1px solid ${C.bd}`,
    background: C.bg,
    color: C.t1,
    fontSize: 12,
    fontFamily: 'inherit',
  } as const;

  return (
    <div
      style={{
        marginTop: 10,
        padding: 10,
        borderRadius: 8,
        background: 'rgba(255,255,255,0.03)',
        border: `1px solid ${C.bd}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>
          Período DOWN:{' '}
          <span style={{ fontFamily: "'JetBrains Mono',monospace", color: C.rd }}>
            {editingDown.id}
          </span>
          <span style={{ fontSize: 12, fontWeight: 400, color: C.t4, marginLeft: 6 }}>
            ({editingDown.type === 'machine' ? 'máquina' : 'ferramenta'})
          </span>
        </span>
        <button
          onClick={() => setEditingDown(null)}
          aria-label="Fechar editor"
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: C.t4,
            padding: 2,
          }}
        >
          <X size={12} />
        </button>
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: C.t3, minWidth: 30 }}>De:</span>
        <select
          value={downStartDay}
          onChange={(e) => {
            const v = Number(e.target.value);
            setDownStartDay(v);
            if (downEndDay < v) setDownEndDay(v);
          }}
          style={selectStyle}
        >
          {wdi.map((i) => (
            <option key={i} value={i}>
              {dnames[i]} {dates[i]}
            </option>
          ))}
        </select>
        <span style={{ fontSize: 12, color: C.t4 }}>até</span>
        <select
          value={downEndDay}
          onChange={(e) => setDownEndDay(Number(e.target.value))}
          style={selectStyle}
        >
          {wdi
            .filter((i) => i >= downStartDay)
            .map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
        </select>
        <button
          onClick={() => {
            const days: number[] = [];
            for (let d = downStartDay; d <= downEndDay; d++) days.push(d);
            setResourceDown(editingDown.type, editingDown.id, days);
          }}
          style={{
            padding: '3px 10px',
            borderRadius: 4,
            border: 'none',
            background: C.rd,
            color: C.t1,
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Aplicar
        </button>
      </div>
      {currentDown.size > 0 && (
        <div style={{ display: 'flex', gap: 2, marginBottom: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: C.t4, minWidth: 30 }}>Dias:</span>
          {dates.map((_d: string, i: number) => (
            <div
              key={i}
              style={{
                width: 6,
                height: 18,
                borderRadius: 2,
                background: currentDown.has(i) ? C.rd : `${C.bd}44`,
              }}
              title={`${dnames[i]} ${dates[i]}${currentDown.has(i) ? ' — DOWN' : ''}`}
            />
          ))}
          <span style={{ fontSize: 12, color: C.rd, fontWeight: 600, marginLeft: 4 }}>
            {currentDown.size}d
          </span>
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={() =>
            setResourceDown(
              editingDown.type,
              editingDown.id,
              dates.map((_: string, i: number) => i),
            )
          }
          style={{
            padding: '3px 10px',
            borderRadius: 4,
            border: `1px solid ${C.rd}44`,
            background: C.rdS,
            color: C.rd,
            fontSize: 12,
            cursor: 'pointer',
            fontFamily: 'inherit',
            fontWeight: 600,
          }}
        >
          Tudo DOWN
        </button>
        <button
          onClick={() => clearResourceDown(editingDown.type, editingDown.id)}
          style={{
            padding: '3px 10px',
            borderRadius: 4,
            border: `1px solid ${C.bd}`,
            background: 'transparent',
            color: C.t3,
            fontSize: 12,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Limpar
        </button>
      </div>
    </div>
  );
}
