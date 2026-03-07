import { Loader, Upload } from 'lucide-react';

interface FileUploaderProps {
  dragActive: boolean;
  processing: boolean;
  processingFileName?: string;
  onDrop: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onClick: () => void;
}

export default function FileUploader({
  dragActive,
  processing,
  processingFileName,
  onDrop,
  onDragOver,
  onDragLeave,
  onClick,
}: FileUploaderProps) {
  if (processing) {
    return (
      <div className="carregar-dados__processing">
        <Loader size={18} className="carregar-dados__processing-spinner" />
        <span className="carregar-dados__processing-text">A processar {processingFileName}...</span>
      </div>
    );
  }

  return (
    <div
      className={`carregar-dados__dropzone ${dragActive ? 'carregar-dados__dropzone--active' : ''}`}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onClick={onClick}
      data-testid="dropzone"
    >
      <Upload size={28} className="carregar-dados__dropzone-icon" />
      <span className="carregar-dados__dropzone-text">Arraste o ISOP .xlsx aqui</span>
      <span className="carregar-dados__dropzone-hint">ou clique para selecionar ficheiro</span>
    </div>
  );
}
