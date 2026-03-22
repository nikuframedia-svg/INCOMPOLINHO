/**
 * MachineDetail — Context panel content for a selected machine.
 */

import { Calendar, Cpu } from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DayLoad } from '@/domain/types/scheduling';
import { DAY_CAP } from '@/domain/types/scheduling';
import { useScheduleData } from '../../hooks/useScheduleData';
import { useUIStore } from '../../stores/useUIStore';
import { LoadBar, Section, Stat } from './ContextPanelPrimitives';

export function MachineDetail({ machineId }: { machineId: string }) {
  const navigate = useNavigate();
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const { engine, cap, blocks, validation } = useScheduleData();

  const machine = engine?.machines.find((m) => m.id === machineId);
  const machCap = cap[machineId] || [];
  const machineTools = useMemo(
    () => engine?.tools.filter((t) => t.m === machineId || t.alt === machineId) || [],
    [engine, machineId],
  );
  const machineBlocks = useMemo(
    () => blocks.filter((b) => b.machineId === machineId),
    [blocks, machineId],
  );

  const avgUtil =
    machCap.length > 0
      ? machCap.reduce((s: number, d: DayLoad) => s + (d.prod + d.setup) / DAY_CAP, 0) /
        machCap.length
      : 0;

  const totalProd = machCap.reduce((s: number, d: DayLoad) => s + d.prod, 0);
  const totalSetup = machCap.reduce((s: number, d: DayLoad) => s + d.setup, 0);
  const totalPcs = machCap.reduce((s: number, d: DayLoad) => s + d.pcs, 0);

  // Violations for this machine
  const machineViolations = useMemo(() => {
    if (!validation) return [];
    return validation.violations.filter((v) =>
      v.affectedOps.some((op) => op.machineId === machineId),
    );
  }, [validation, machineId]);

  if (!machine)
    return (
      <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        Máquina não encontrada.
      </div>
    );

  return (
    <>
      <Section title="Detalhe">
        <Stat label="Area" value={machine.area} />
        <Stat
          label="Util. Media"
          value={`${(avgUtil * 100).toFixed(0)}%`}
          variant={avgUtil > 1 ? 'red' : avgUtil > 0.85 ? 'amber' : 'green'}
        />
        <Stat label="Produção Total" value={`${totalProd.toFixed(0)} min`} />
        <Stat label="Setup Total" value={`${totalSetup.toFixed(0)} min`} />
        <Stat label="Pecas" value={totalPcs.toLocaleString()} />
        <Stat label="Ferramentas" value={String(machineTools.length)} />
        <Stat label="Operações" value={String(machineBlocks.length)} />

        {/* Per-day load bars */}
        {machCap.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
              Carga por dia
            </div>
            {machCap.map((d: DayLoad, di: number) => (
              <div
                key={di}
                style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}
              >
                <span
                  style={{
                    width: 24,
                    fontSize: 12,
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-ghost)',
                    textAlign: 'right',
                  }}
                >
                  {engine?.dnames[di] || `D${di}`}
                </span>
                <LoadBar prod={d.prod} setup={d.setup} cap={DAY_CAP} />
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Problemas" defaultOpen={machineViolations.length > 0}>
        {machineViolations.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--semantic-green)' }}>
            Sem violações para esta máquina.
          </div>
        ) : (
          machineViolations.map((v, i) => (
            <div key={i} className="ctx-panel__violation">
              <span
                className={`ctx-panel__violation-dot ctx-panel__violation-dot--${v.severity === 'critical' ? 'critical' : 'warning'}`}
              />
              <span className="ctx-panel__violation-text">{v.title}</span>
            </div>
          ))
        )}
      </Section>

      <Section title="Accoes Rapidas">
        <div className="ctx-panel__actions">
          <button
            className="ctx-panel__action-btn"
            onClick={() => {
              setFocus({ machine: machineId });
              navigate('/plan');
            }}
            data-testid="ctx-open-planning"
          >
            <Calendar size={14} />
            Abrir em Planning
          </button>
          <button
            className="ctx-panel__action-btn"
            onClick={() => {
              setFocus({ machine: machineId });
              navigate('/console');
            }}
            data-testid="ctx-open-fabrica"
          >
            <Cpu size={14} />
            Ver na Fabrica
          </button>
        </div>
      </Section>
    </>
  );
}
