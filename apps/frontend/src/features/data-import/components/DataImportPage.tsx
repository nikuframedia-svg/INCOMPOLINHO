import { CalendarDays } from 'lucide-react';
import type { DemandSemantics } from '../../../stores/useSettingsStore';
import { useSettingsStore } from '../../../stores/useSettingsStore';
import { useUIStore } from '../../../stores/useUIStore';
import { SEMANTICS_OPTIONS, useIsopParser } from '../hooks/useIsopParser';
import { DataPreview } from './DataPreview';
import { DataValidation } from './DataValidation';
import { FileUploader } from './FileUploader';
import { ImportConfirmation } from './ImportConfirmation';
import { MOStrategySection } from './MOStrategySection';
import { MRPSupplySection } from './MRPSupplySection';
import { OptimizationProfileSection } from './OptimizationProfileSection';
import { OverflowRoutingSection } from './OverflowRoutingSection';
import { PlanningRulesSection } from './PlanningRulesSection';
import { ShiftsCapacitySection } from './ShiftsCapacitySection';
import './CarregarDados.css';

export function DataImportPage() {
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  const semantics = useSettingsStore((s) => s.demandSemantics);
  const setDemandSemantics = useSettingsStore((s) => s.actions.setDemandSemantics);

  const {
    uploadState,
    setUploadState,
    dragActive,
    setDragActive,
    fileRef,
    hasData,
    loadedAt,
    storedFileName,
    storedMeta,
    handleDrop,
    handleFileInput,
    handleApply,
    handleClear,
  } = useIsopParser();

  return (
    <div className={`carregar-dados${panelOpen ? ' carregar-dados--panel-open' : ''}`}>
      <input
        ref={fileRef}
        type="file"
        accept=".xlsx,.xls"
        onChange={handleFileInput}
        style={{ display: 'none' }}
        data-testid="file-input"
      />

      <div className="carregar-dados__header">
        <h2 className="carregar-dados__title">Definicoes do Sistema</h2>
        <p className="carregar-dados__desc">
          Importe o ISOP e configure os parametros do motor de planeamento.
        </p>
      </div>

      <div className="carregar-dados__section">
        <div className="carregar-dados__section-header">
          <div className="carregar-dados__section-icon carregar-dados__section-icon--daily">
            <CalendarDays size={16} />
          </div>
          <div>
            <div className="carregar-dados__section-title">ISOP — Plano de Producao</div>
            <div className="carregar-dados__section-subtitle">
              Demand, clientes, stock, WIP, atraso, datas de producao
            </div>
          </div>
        </div>

        {hasData && storedMeta && loadedAt && uploadState.step === 'idle' && (
          <ImportConfirmation
            fileName={storedFileName ?? ''}
            loadedAt={loadedAt}
            meta={storedMeta}
            onNewUpload={() => fileRef.current?.click()}
            onClear={handleClear}
          />
        )}

        {(uploadState.step === 'idle' || uploadState.step === 'error') && !hasData && (
          <FileUploader
            dragActive={dragActive}
            processing={false}
            onDrop={handleDrop}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onClick={() => fileRef.current?.click()}
          />
        )}

        {uploadState.step === 'processing' && (
          <FileUploader
            dragActive={false}
            processing={true}
            processingFileName={uploadState.fileName}
            onDrop={handleDrop}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onClick={() => fileRef.current?.click()}
          />
        )}

        {uploadState.step === 'error' && (
          <DataValidation errors={uploadState.errors} fileName={uploadState.fileName} />
        )}

        {uploadState.step === 'preview' && (
          <DataPreview
            fileName={uploadState.fileName}
            meta={uploadState.meta}
            warnings={uploadState.meta.warnings}
            onApply={handleApply}
            onCancel={() => setUploadState({ step: 'idle' })}
          />
        )}
      </div>

      <div className="carregar-dados__semantics">
        <span className="carregar-dados__semantics-label">Semantica dos dados:</span>
        <select
          className="carregar-dados__semantics-select"
          value={semantics}
          onChange={(e) => setDemandSemantics(e.target.value as DemandSemantics)}
          data-testid="semantics-select"
        >
          {SEMANTICS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <ShiftsCapacitySection />
      <PlanningRulesSection />
      <OptimizationProfileSection />
      <MOStrategySection />
      <OverflowRoutingSection />
      <MRPSupplySection />
    </div>
  );
}
