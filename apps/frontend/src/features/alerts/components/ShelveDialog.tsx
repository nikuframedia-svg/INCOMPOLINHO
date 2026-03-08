import { useState } from 'react';
import type { Alert } from '../alert-types';
import { useAlertStore } from '../useAlertStore';
import '../alerts.css';

const PRESETS = [
  { label: '15m', min: 15 },
  { label: '30m', min: 30 },
  { label: '1h', min: 60 },
  { label: '4h', min: 240 },
  { label: '8h', min: 480 },
];

interface ShelveDialogProps {
  alert: Alert;
  onClose: () => void;
}

export function ShelveDialog({ alert, onClose }: ShelveDialogProps) {
  const shelve = useAlertStore((s) => s.shelve);
  const [reason, setReason] = useState('');
  const [durationMin, setDurationMin] = useState(30);

  const handleSubmit = () => {
    if (!reason.trim()) return;
    shelve(alert.id, reason.trim(), durationMin);
    onClose();
  };

  return (
    <div className="shelve-dialog" data-testid="shelve-dialog">
      <div className="shelve-dialog__title">Pausar alarme — {alert.source}</div>

      <div className="shelve-dialog__field">
        <label className="shelve-dialog__label" htmlFor="shelve-reason">
          Justificacao (obrigatorio)
        </label>
        <input
          id="shelve-reason"
          className="shelve-dialog__input"
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Motivo da pausa..."
          data-testid="shelve-reason-input"
        />
      </div>

      <div className="shelve-dialog__field">
        <span className="shelve-dialog__label">Duracao</span>
        <div className="shelve-dialog__presets">
          {PRESETS.map((p) => (
            <button
              key={p.min}
              type="button"
              className={`shelve-dialog__preset${durationMin === p.min ? ' shelve-dialog__preset--active' : ''}`}
              onClick={() => setDurationMin(p.min)}
              data-testid={`shelve-preset-${p.min}`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="shelve-dialog__actions">
        <button
          type="button"
          className="shelve-dialog__btn"
          onClick={onClose}
          data-testid="shelve-cancel"
        >
          Cancelar
        </button>
        <button
          type="button"
          className="shelve-dialog__btn shelve-dialog__btn--primary"
          onClick={handleSubmit}
          disabled={!reason.trim()}
          data-testid="shelve-confirm"
        >
          Pausar {PRESETS.find((p) => p.min === durationMin)?.label ?? `${durationMin}m`}
        </button>
      </div>
    </div>
  );
}
