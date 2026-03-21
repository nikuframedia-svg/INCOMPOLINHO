/**
 * ShiftsPage — Shift calendar configuration per machine.
 * Route: /settings/shifts
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { DEFAULT_WORKFORCE_CONFIG } from '@/lib/engine';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { ShiftCalendarEditor } from '../components/ShiftCalendarEditor';

interface ShiftException {
  id: string;
  date: string;
  machine: string;
  reason: string;
}

export function ShiftsPage() {
  const { engine, loading, error, thirdShiftRecommended } = useScheduleData();
  const thirdShiftDefault = useSettingsStore((s) => s.thirdShiftDefault);
  const setThirdShiftDefault = useSettingsStore((s) => s.actions.setThirdShiftDefault);
  const [exceptions, setExceptions] = useState<ShiftException[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [formDate, setFormDate] = useState('');
  const [formMachine, setFormMachine] = useState('');
  const [formReason, setFormReason] = useState('');

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={5} cols={7} />
      </div>
    );
  if (error || !engine) {
    return (
      <div style={{ padding: 32 }}>
        <Link
          to="/settings"
          style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
        >
          ← Settings
        </Link>
        <EmptyState icon="error" title="Sem dados" description={error || 'Importe ISOP.'} />
      </div>
    );
  }

  const machines = engine.machines.map((m) => m.id);
  const laborGroupMap = DEFAULT_WORKFORCE_CONFIG.machineToLaborGroup;
  const laborCapacities: Record<string, number[]> = {};
  for (const [group, windows] of Object.entries(DEFAULT_WORKFORCE_CONFIG.laborGroups)) {
    laborCapacities[group] = windows.map((w) => w.capacity);
  }

  const addException = () => {
    if (!formDate || !formMachine || !formReason) return;
    setExceptions((prev) => [
      ...prev,
      { id: crypto.randomUUID(), date: formDate, machine: formMachine, reason: formReason },
    ]);
    setFormDate('');
    setFormMachine('');
    setFormReason('');
    setShowForm(false);
  };

  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Link to="/settings" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
        ← Settings
      </Link>
      <h2
        style={{
          color: 'var(--text-primary)',
          fontSize: 'var(--text-h3)',
          fontWeight: 600,
          margin: 0,
        }}
      >
        Calendário de Turnos
      </h2>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          padding: '12px 16px',
          border: `1px solid ${thirdShiftRecommended && !thirdShiftDefault ? 'var(--semantic-warning, #FF8C00)' : 'var(--border-default)'}`,
          borderRadius: 8,
          background: thirdShiftRecommended && !thirdShiftDefault ? 'rgba(255, 140, 0, 0.06)' : 'transparent',
        }}
      >
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--text-primary)',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={thirdShiftDefault}
            onChange={(e) => setThirdShiftDefault(e.target.checked)}
          />
          3.o turno (Z: 00:00-07:00) activo por defeito
        </label>
        {thirdShiftRecommended && !thirdShiftDefault && (
          <div
            style={{
              fontSize: 12,
              color: 'var(--semantic-warning, #FF8C00)',
              fontWeight: 600,
            }}
          >
            2 turnos insuficientes — turno noite recomendado para resolver overflow
          </div>
        )}
      </div>

      <ShiftCalendarEditor
        machines={machines}
        laborGroupMap={laborGroupMap}
        laborCapacities={laborCapacities}
      />

      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            Excepções
          </span>
          <button
            className="constraint-toggles__param-select"
            style={{ cursor: 'pointer', fontSize: 12, padding: '3px 10px' }}
            onClick={() => setShowForm(!showForm)}
          >
            {showForm ? 'Cancelar' : '+ Adicionar'}
          </button>
        </div>

        {showForm && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'flex-end' }}>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block' }}>
                Data
              </label>
              <input
                type="date"
                value={formDate}
                onChange={(e) => setFormDate(e.target.value)}
                className="constraint-toggles__param-select"
                style={{ fontSize: 12 }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block' }}>
                Máquina
              </label>
              <select
                value={formMachine}
                onChange={(e) => setFormMachine(e.target.value)}
                className="constraint-toggles__param-select"
                style={{ fontSize: 12 }}
              >
                <option value="">—</option>
                {machines.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block' }}>
                Motivo
              </label>
              <input
                type="text"
                value={formReason}
                onChange={(e) => setFormReason(e.target.value)}
                placeholder="Feriado, manutenção..."
                className="constraint-toggles__param-select"
                style={{ fontSize: 12, width: 160 }}
              />
            </div>
            <button
              className="constraint-toggles__param-select"
              style={{
                cursor: 'pointer',
                fontSize: 12,
                padding: '3px 10px',
                background: 'var(--accent)',
                color: 'var(--bg-base)',
                border: 'none',
                borderRadius: 4,
              }}
              onClick={addException}
            >
              Guardar
            </button>
          </div>
        )}

        {exceptions.length === 0 && !showForm && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sem excepções definidas</div>
        )}
        {exceptions.map((ex) => (
          <div
            key={ex.id}
            style={{
              display: 'flex',
              gap: 12,
              fontSize: 12,
              color: 'var(--text-secondary)',
              padding: '4px 0',
              borderBottom: '1px solid var(--border-default)',
            }}
          >
            <span style={{ fontFamily: 'var(--font-mono)' }}>{ex.date}</span>
            <span style={{ fontWeight: 500 }}>{ex.machine}</span>
            <span>{ex.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
