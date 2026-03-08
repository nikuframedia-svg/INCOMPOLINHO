import { useState } from 'react';
import type { Alert, AlertPriority } from '../alert-types';
import {
  classifyEEMUA,
  EEMUA_COLORS,
  EEMUA_LABELS,
  PRIORITY_COLORS,
  PRIORITY_LABELS,
} from '../alert-types';
import { useActiveAlerts, useAlertStore, useStandingCount, useUnackCount } from '../useAlertStore';
import { AlertRow } from './AlertRow';
import { ShelveDialog } from './ShelveDialog';
import '../alerts.css';

const PRIORITIES: AlertPriority[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

export function AlertPanel() {
  const alarmsPerTenMin = useAlertStore((s) => s.alarmsPerTenMin);
  const activeAlerts = useActiveAlerts();
  const standingCount = useStandingCount();
  const unackCount = useUnackCount();

  const [filterPriority, setFilterPriority] = useState<AlertPriority | null>(null);
  const [shelveTarget, setShelveTarget] = useState<Alert | null>(null);

  const eemua = classifyEEMUA(alarmsPerTenMin);
  const eColor = EEMUA_COLORS[eemua];

  const filtered = filterPriority
    ? activeAlerts.filter((a) => a.priority === filterPriority)
    : activeAlerts;

  const countByPriority = (p: AlertPriority) => activeAlerts.filter((a) => a.priority === p).length;

  return (
    <div className="alert-panel" data-testid="alert-panel">
      {/* Header */}
      <div className="alert-panel__header">
        <span className="alert-panel__title">Painel de Alarmes</span>

        <div className="alert-panel__stat">
          <span className="alert-panel__stat-value">{alarmsPerTenMin}</span>
          <span className="alert-panel__stat-label">Alarmes/10min</span>
        </div>

        <div className="alert-panel__stat">
          <span className="alert-panel__stat-value">{standingCount}</span>
          <span className="alert-panel__stat-label">Activos</span>
        </div>

        <div className="alert-panel__stat">
          <span className="alert-panel__stat-value">{unackCount}</span>
          <span className="alert-panel__stat-label">Nao Reconhecidos</span>
        </div>

        <span
          className="alert-panel__eemua"
          style={{ background: `${eColor}18`, color: eColor }}
          data-testid="eemua-badge"
        >
          <span className="alert-panel__eemua-icon" style={{ background: eColor }} />
          {EEMUA_LABELS[eemua]}
        </span>
      </div>

      {/* Priority filter tabs */}
      <div className="alert-panel__priority-tabs">
        <button
          type="button"
          className={`alert-panel__priority-tab${filterPriority === null ? ' alert-panel__priority-tab--active' : ''}`}
          onClick={() => setFilterPriority(null)}
        >
          Todos
          <span className="alert-panel__priority-count">{activeAlerts.length}</span>
        </button>
        {PRIORITIES.map((p) => {
          const count = countByPriority(p);
          return (
            <button
              key={p}
              type="button"
              className={`alert-panel__priority-tab${filterPriority === p ? ' alert-panel__priority-tab--active' : ''}`}
              onClick={() => setFilterPriority(filterPriority === p ? null : p)}
              data-testid={`priority-tab-${p}`}
            >
              <span
                className="alert-panel__priority-dot"
                style={{ background: PRIORITY_COLORS[p] }}
              />
              {PRIORITY_LABELS[p]}
              <span className="alert-panel__priority-count">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Alert list */}
      <div className="alert-panel__list">
        {filtered.length === 0 ? (
          <div className="alert-panel__empty">
            {filterPriority
              ? `Sem alarmes ${PRIORITY_LABELS[filterPriority].toLowerCase()} activos`
              : 'Sem alarmes activos'}
          </div>
        ) : (
          filtered.map((alert) => (
            <AlertRow key={alert.id} alert={alert} onShelve={setShelveTarget} />
          ))
        )}
      </div>

      {/* Shelve dialog overlay */}
      {shelveTarget && <ShelveDialog alert={shelveTarget} onClose={() => setShelveTarget(null)} />}
    </div>
  );
}
