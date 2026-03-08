import { XCircle } from 'lucide-react';

interface DataValidationProps {
  errors: string[];
  fileName: string;
}

export function DataValidation({ errors, fileName }: DataValidationProps) {
  return (
    <>
      <div className="carregar-dados__preview-header">
        <span className="carregar-dados__preview-title">Erros em {fileName}</span>
        <span className="carregar-dados__trust-badge carregar-dados__trust-badge--red">
          <XCircle size={14} /> Erro
        </span>
      </div>
      <div className="carregar-dados__warnings">
        {errors.map((err, i) => (
          <div key={i} className="carregar-dados__warning carregar-dados__warning--error">
            {err}
          </div>
        ))}
      </div>
    </>
  );
}
