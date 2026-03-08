import { useState } from 'react';
import type { Alert } from '../alert-types';
import { isFlashing, PRIORITY_BG, PRIORITY_COLORS, PRIORITY_LABELS } from '../alert-types';
import { useAlertStore } from '../useAlertStore';
import '../alerts.css';

const STATE_LABELS: Record<string, string> = {
  UNACK_ACTIVE: 'Nao Reconhecido',
  ACK_ACTIVE: 'Reconhecido',
  RTN_UNACK: 'Retornou (nao ack)',
  SHELVED: 'Em Pausa',
  SUPPRESSED: 'Suprimido',
  NORMAL: 'Normal',
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function shelveRemaining(expiresAt: string | undefined): string | null {
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return 'Expirado';
  const min = Math.ceil(diff / 60_000);
  if (min >= 60) return `${Math.floor(min / 60)}h ${min % 60}m`;
  return `${min}m`;
}

interface AlertRowProps {
  alert: Alert;
  onShelve?: (alert: Alert) => void;
  onDrillDown?: (alert: Alert) => void;
}

export function AlertRow({ alert, onShelve, onDrillDown }: AlertRowProps) {
  const acknowledge = useAlertStore((s) => s.acknowledge);
  const [expanded, setExpanded] = useState(false);

  const color = PRIORITY_COLORS[alert.priority];
  const bg = PRIORITY_BG[alert.priority];
  const flash = isFlashing(alert.state);
  const canAck = alert.state === 'UNACK_ACTIVE' || alert.state === 'RTN_UNACK';
  const isShelved = alert.state === 'SHELVED';
  const isSuppressed = alert.state === 'SUPPRESSED';
  const remaining = shelveRemaining(alert.shelveExpiresAt);

  return (
    <div
      className="alert-row"
      style={{ borderColor: `${color}30` }}
      data-testid={`alert-row-${alert.id}`}
    >
      {/* Priority bar */}
      <div className="alert-row__priority-bar" style={{ background: color }} />

      {/* State indicator */}
      {isShelved ? (
        <span className="alert-row__shelve-badge" title="Em Pausa">
          S
        </span>
      ) : isSuppressed ? (
        <span className="alert-row__shelve-badge" title="Suprimido">
          X
        </span>
      ) : (
        <div
          className={`alert-row__indicator${flash ? ' alert-row__indicator--flash' : ''}`}
          style={{ background: bg, color }}
          title={STATE_LABELS[alert.state]}
        >
          {alert.priority[0]}
        </div>
      )}

      {/* Content */}
      <div className="alert-row__content">
        <div className="alert-row__top">
          <span className="alert-row__source">{alert.source}</span>
          <span className="alert-row__priority-label" style={{ background: bg, color }}>
            {PRIORITY_LABELS[alert.priority]}
          </span>
          <span className="alert-row__state-label">{STATE_LABELS[alert.state]}</span>
          <span className="alert-row__time">{formatTime(alert.activatedAt)}</span>
        </div>

        <div className="alert-row__cause">{alert.cause}</div>

        {expanded && (
          <div className="alert-row__details">
            <div>
              <span className="alert-row__detail-label">Consequencia:</span>
              {alert.consequence}
            </div>
            <div>
              <span className="alert-row__detail-label">Accao correctiva:</span>
              {alert.correctiveAction}
            </div>
            {alert.acknowledgedAt && (
              <div>
                <span className="alert-row__detail-label">Reconhecido:</span>
                {formatTime(alert.acknowledgedAt)}
              </div>
            )}
          </div>
        )}

        {isShelved && remaining && (
          <div className="alert-row__shelve-info">
            Pausa: {alert.shelveReason} — {remaining} restante
          </div>
        )}
        {isSuppressed && alert.suppressionReason && (
          <div className="alert-row__shelve-info">Suprimido: {alert.suppressionReason}</div>
        )}
      </div>

      {/* Actions */}
      <div className="alert-row__actions">
        <button
          type="button"
          className="alert-row__action-btn"
          onClick={() => setExpanded(!expanded)}
          data-testid={`alert-expand-${alert.id}`}
        >
          {expanded ? 'Menos' : 'Detalhe'}
        </button>

        {canAck && (
          <button
            type="button"
            className="alert-row__action-btn alert-row__action-btn--primary"
            onClick={() => acknowledge(alert.id)}
            data-testid={`alert-ack-${alert.id}`}
          >
            Reconhecer
          </button>
        )}

        {!isShelved && !isSuppressed && alert.state !== 'NORMAL' && onShelve && (
          <button
            type="button"
            className="alert-row__action-btn"
            onClick={() => onShelve(alert)}
            data-testid={`alert-shelve-${alert.id}`}
          >
            Pausar
          </button>
        )}

        {onDrillDown && (
          <button
            type="button"
            className="alert-row__action-btn"
            onClick={() => onDrillDown(alert)}
            data-testid={`alert-drill-${alert.id}`}
          >
            Investigar
          </button>
        )}
      </div>
    </div>
  );
}
