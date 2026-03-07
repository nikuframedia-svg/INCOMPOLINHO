import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react';
import type { LoadMeta } from '../../../stores/useDataStore';

interface DataPreviewProps {
  fileName: string;
  meta: LoadMeta;
  warnings: string[];
  onApply: () => void;
  onCancel: () => void;
}

function trustBadgeClass(score: number): string {
  if (score >= 0.85) return 'carregar-dados__trust-badge--green';
  if (score >= 0.7) return 'carregar-dados__trust-badge--amber';
  return 'carregar-dados__trust-badge--red';
}

function trustIcon(score: number) {
  if (score >= 0.85) return <CheckCircle size={14} />;
  if (score >= 0.7) return <AlertTriangle size={14} />;
  return <XCircle size={14} />;
}

function SummaryGrid({ meta }: { meta: LoadMeta }) {
  return (
    <div className="carregar-dados__summary">
      <div className="carregar-dados__stat">
        <span className="carregar-dados__stat-value">{meta.rows}</span>
        <span className="carregar-dados__stat-label">Linhas</span>
      </div>
      <div className="carregar-dados__stat">
        <span className="carregar-dados__stat-value">{meta.machines}</span>
        <span className="carregar-dados__stat-label">Maquinas</span>
      </div>
      <div className="carregar-dados__stat">
        <span className="carregar-dados__stat-value">{meta.tools}</span>
        <span className="carregar-dados__stat-label">Ferramentas</span>
      </div>
      <div className="carregar-dados__stat">
        <span className="carregar-dados__stat-value">{meta.skus}</span>
        <span className="carregar-dados__stat-label">SKUs</span>
      </div>
      <div className="carregar-dados__stat">
        <span className="carregar-dados__stat-value">{meta.dates}</span>
        <span className="carregar-dados__stat-label">Dias totais</span>
      </div>
      <div className="carregar-dados__stat">
        <span className="carregar-dados__stat-value">{meta.workdays}</span>
        <span className="carregar-dados__stat-label">Dias uteis</span>
      </div>
    </div>
  );
}

export { SummaryGrid, trustBadgeClass, trustIcon };

export default function DataPreview({
  fileName,
  meta,
  warnings,
  onApply,
  onCancel,
}: DataPreviewProps) {
  return (
    <div className="carregar-dados__preview">
      <div className="carregar-dados__preview-header">
        <span className="carregar-dados__preview-title">{fileName}</span>
        <span className={`carregar-dados__trust-badge ${trustBadgeClass(meta.trustScore)}`}>
          {trustIcon(meta.trustScore)}
          {Math.round(meta.trustScore * 100)}%
        </span>
      </div>
      <SummaryGrid meta={meta} />
      {warnings.length > 0 && (
        <div className="carregar-dados__warnings">
          {warnings.map((w, i) => (
            <div key={i} className="carregar-dados__warning">
              {w}
            </div>
          ))}
        </div>
      )}
      <div className="carregar-dados__actions">
        <button
          className="carregar-dados__btn carregar-dados__btn--primary"
          onClick={onApply}
          data-testid="btn-apply"
        >
          Aplicar Dados
        </button>
        <button
          className="carregar-dados__btn carregar-dados__btn--secondary"
          onClick={onCancel}
          data-testid="btn-cancel"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
}
