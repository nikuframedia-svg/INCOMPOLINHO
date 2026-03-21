/**
 * ContextPanel — Right-side inspector panel.
 *
 * Updates reactively when a machine or tool is selected.
 * 3 collapsible sections: Entity Detail, Related Problems, Quick Actions.
 * Close with Esc or X button.
 */

import { AlertTriangle, ArrowRight, Calendar, ChevronRight, Cpu, Wrench, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useScheduleData } from '../../hooks/useScheduleData';
import type { DayLoad } from '../../lib/engine';
import { DAY_CAP } from '../../lib/engine';
import { useUIStore } from '../../stores/useUIStore';
import './ContextPanel.css';

// ── Collapsible section ────────────────────────────────────
function Section({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ctx-panel__section">
      <div className="ctx-panel__section-header" role="button" tabIndex={0} onClick={() => setOpen((o) => !o)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((o) => !o); } }}>
        <span className="ctx-panel__section-title">{title}</span>
        <span
          className={`ctx-panel__section-chevron ${open ? 'ctx-panel__section-chevron--open' : ''}`}
        >
          <ChevronRight size={12} />
        </span>
      </div>
      {open && <div className="ctx-panel__section-content">{children}</div>}
    </div>
  );
}

function Stat({
  label,
  value,
  variant,
}: {
  label: string;
  value: string;
  variant?: 'green' | 'amber' | 'red';
}) {
  return (
    <div className="ctx-panel__stat">
      <span className="ctx-panel__stat-label">{label}</span>
      <span
        className={`ctx-panel__stat-value ${variant ? `ctx-panel__stat-value--${variant}` : ''}`}
      >
        {value}
      </span>
    </div>
  );
}

function LoadBar({ prod, setup, cap }: { prod: number; setup: number; cap: number }) {
  const total = prod + setup;
  const pPct = cap > 0 ? (prod / cap) * 100 : 0;
  const sPct = cap > 0 ? (setup / cap) * 100 : 0;
  const uPct = cap > 0 ? (total / cap) * 100 : 0;
  return (
    <div className="ctx-panel__bar-wrap">
      <div className="ctx-panel__bar">
        <div
          className="ctx-panel__bar-seg ctx-panel__bar-seg--prod"
          style={{ width: `${Math.min(pPct, 100)}%` }}
        />
        <div
          className="ctx-panel__bar-seg ctx-panel__bar-seg--setup"
          style={{ width: `${Math.min(sPct, 100 - Math.min(pPct, 100))}%` }}
        />
      </div>
      <span className="ctx-panel__bar-label">{uPct.toFixed(0)}%</span>
    </div>
  );
}

// ── Machine detail panel ───────────────────────────────────
function MachineDetail({ machineId }: { machineId: string }) {
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

// ── Tool detail panel ──────────────────────────────────────
function ToolDetail({ toolId }: { toolId: string }) {
  const navigate = useNavigate();
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const { engine, blocks } = useScheduleData();

  const tool = engine?.tools.find((t) => t.id === toolId);
  const toolOps = useMemo(() => engine?.ops.filter((o) => o.t === toolId) || [], [engine, toolId]);
  const toolBlocks = useMemo(() => blocks.filter((b) => b.toolId === toolId), [blocks, toolId]);
  const totalDemand = toolOps.reduce((s, o) => s + o.d.reduce((a, v) => a + v, 0), 0);
  const totalBacklog = toolOps.reduce((s, o) => s + o.atr, 0);

  if (!tool)
    return (
      <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        Ferramenta nao encontrada.
      </div>
    );

  return (
    <>
      <Section title="Detalhe">
        <Stat label="Máquina Primária" value={tool.m} />
        <Stat label="Máquina Alternativa" value={tool.alt || 'Nenhuma'} />
        <Stat label="Rate" value={`${tool.pH} pcs/h`} />
        <Stat label="Setup" value={`${tool.sH}h`} />
        <Stat label="Operadores" value={String(tool.op)} />
        <Stat
          label="Stock"
          value={tool.stk.toLocaleString()}
          variant={tool.stk <= 0 ? 'red' : tool.stk < tool.lt ? 'amber' : undefined}
        />
        <Stat label="Lote Economico" value={tool.lt.toLocaleString()} />
        <Stat label="Demand Total" value={totalDemand.toLocaleString()} />
        {totalBacklog > 0 && (
          <Stat label="Backlog" value={totalBacklog.toLocaleString()} variant="amber" />
        )}
        <Stat label="Operações" value={String(toolOps.length)} />
        <Stat label="Blocos Agendados" value={String(toolBlocks.length)} />
      </Section>

      <Section title="Accoes Rapidas">
        <div className="ctx-panel__actions">
          <button
            className="ctx-panel__action-btn"
            onClick={() => {
              setFocus({ toolId });
              navigate('/mrp');
            }}
            data-testid="ctx-open-pecas"
          >
            <ArrowRight size={14} />
            Ver em Pecas
          </button>
          <button
            className="ctx-panel__action-btn"
            onClick={() => {
              setFocus({ toolId });
              navigate('/mrp');
            }}
            data-testid="ctx-open-supply"
          >
            <AlertTriangle size={14} />
            Verificar Supply
          </button>
        </div>
      </Section>
    </>
  );
}

// ── Main ContextPanel ──────────────────────────────────────
export function ContextPanel() {
  const isOpen = useUIStore((s) => s.contextPanelOpen);
  const entity = useUIStore((s) => s.contextEntity);
  const close = useUIStore((s) => s.actions.closeContextPanel);

  // Close on Esc
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, close]);

  if (!isOpen || !entity) return null;

  const isMachine = entity.type === 'machine';
  const isTool = entity.type === 'tool';

  return (
    <div className="ctx-panel__backdrop" data-testid="context-panel">
      <div className="ctx-panel__header">
        <span className={`ctx-panel__header-icon ctx-panel__header-icon--${entity.type}`}>
          {isMachine ? <Cpu size={14} /> : <Wrench size={14} />}
        </span>
        <div className="ctx-panel__header-body">
          <div className="ctx-panel__header-title">{entity.id}</div>
          <div className="ctx-panel__header-sub">
            {isMachine ? 'Máquina' : isTool ? 'Ferramenta' : entity.type}
          </div>
        </div>
        <button className="ctx-panel__close" onClick={close} data-testid="ctx-panel-close">
          <X size={16} />
        </button>
      </div>

      <div className="ctx-panel__body">
        {isMachine && <MachineDetail machineId={entity.id} />}
        {isTool && <ToolDetail toolId={entity.id} />}
      </div>
    </div>
  );
}
