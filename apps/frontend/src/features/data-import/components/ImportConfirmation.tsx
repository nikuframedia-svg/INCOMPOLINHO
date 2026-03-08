import { FileSpreadsheet, Trash2 } from 'lucide-react';
import type { LoadMeta } from '../../../stores/useDataStore';
import { SummaryGrid, trustBadgeClass, trustIcon } from './DataPreview';

interface ImportConfirmationProps {
  fileName: string;
  loadedAt: string;
  meta: LoadMeta;
  onNewUpload: () => void;
  onClear: () => void;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
    ' ' +
    d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })
  );
}

export function ImportConfirmation({
  fileName,
  loadedAt,
  meta,
  onNewUpload,
  onClear,
}: ImportConfirmationProps) {
  return (
    <div className="carregar-dados__loaded-info">
      <div className="carregar-dados__current-header">
        <FileSpreadsheet size={18} className="carregar-dados__current-icon" />
        <div className="carregar-dados__current-info">
          <span className="carregar-dados__current-file">{fileName}</span>
          <span className="carregar-dados__current-time">
            Carregado: {formatDateTime(loadedAt)}
          </span>
        </div>
        <div className="carregar-dados__trust-badge-wrap">
          <span className={`carregar-dados__trust-badge ${trustBadgeClass(meta.trustScore)}`}>
            {trustIcon(meta.trustScore)}
            {Math.round(meta.trustScore * 100)}%
          </span>
        </div>
      </div>
      <SummaryGrid meta={meta} />
      <div className="carregar-dados__actions">
        <button
          className="carregar-dados__btn carregar-dados__btn--primary"
          onClick={onNewUpload}
          data-testid="btn-new-isop"
        >
          Carregar Novo ISOP
        </button>
        <button
          className="carregar-dados__btn carregar-dados__btn--secondary"
          onClick={onClear}
          data-testid="btn-clear"
        >
          <Trash2 size={14} />
          Limpar Dados
        </button>
      </div>
    </div>
  );
}
