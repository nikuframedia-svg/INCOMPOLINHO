/**
 * CarregarDados — ISOP data import + system settings page.
 *
 * The user uploads a daily ISOP .xlsx file. Master data (setup times, alt machines,
 * rates, M.O.) comes from the embedded fixture (nikufra_data.json) automatically.
 *
 * Below the upload, 6 settings sections give full control over the scheduling engine:
 *  §1 Turnos e Capacidade — shift times, OEE, 3rd shift
 *  §2 Regras de Planeamento — dispatch rule, bucket window, EDD gap, default setup
 *  §3 Perfil de Optimizacao — 7 score weights + 3 presets
 *  §4 Capacidade de Operadores (M.O.) — strategy, PG1/PG2 nominal/custom
 *  §5 Overflow e Routing — alt threshold, max moves, iterations, OTD tolerance, load balance
 *  §6 MRP e Supply — service level, coverage, ABC/XYZ thresholds
 *
 * When applied, MockDataSource picks up user data and NikufraEngine replans.
 */

import {
  AlertTriangle,
  CalendarDays,
  CheckCircle,
  Clock,
  FileSpreadsheet,
  GitBranch,
  ListOrdered,
  Loader,
  Package,
  SlidersHorizontal,
  Trash2,
  Upload,
  Users,
  XCircle,
} from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import type { ParseError, ParseResult } from '../../domain/isopClientParser';
import { parseISOPFile } from '../../domain/isopClientParser';
import type { NikufraData } from '../../domain/nikufra-types';
import { invalidateScheduleCache } from '../../hooks/useScheduleData';
import type { LoadMeta } from '../../stores/useDataStore';
import useDataStore from '../../stores/useDataStore';
import type {
  DemandSemantics,
  DispatchRule,
  MOStrategy,
  OptimizationProfile,
  ServiceLevelOption,
} from '../../stores/useSettingsStore';
import useSettingsStore, { getEngineConfig } from '../../stores/useSettingsStore';
import useUIStore from '../../stores/useUIStore';
import './CarregarDados.css';

type UploadState =
  | { step: 'idle' }
  | { step: 'processing'; fileName: string }
  | { step: 'preview'; data: NikufraData; meta: LoadMeta; fileName: string }
  | { step: 'error'; errors: string[]; fileName: string };

const SEMANTICS_OPTIONS: { value: DemandSemantics; label: string }[] = [
  { value: 'raw_np', label: 'Posicao liquida bruta (padrao)' },
  { value: 'cumulative_np', label: 'Posicao liquida cumulativa' },
  { value: 'daily', label: 'Quantidade diaria' },
];

function CarregarDados() {
  const {
    nikufraData,
    loadedAt,
    fileName: storedFileName,
    meta: storedMeta,
    setNikufraData,
    clearData,
  } = useDataStore();

  const panelOpen = useUIStore((s) => s.contextPanelOpen);

  const semantics = useSettingsStore((s) => s.demandSemantics);
  const setDemandSemantics = useSettingsStore((s) => s.setDemandSemantics);

  const [uploadState, setUploadState] = useState<UploadState>({ step: 'idle' });
  const [dragActive, setDragActive] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);

  const hasData = nikufraData !== null;

  // ── Parse logic ──

  const processFile = useCallback(
    async (file: File) => {
      setUploadState({ step: 'processing', fileName: file.name });
      try {
        const buffer = await file.arrayBuffer();
        const result = parseISOPFile(buffer, semantics);
        if (result.success) {
          const r = result as ParseResult;
          setUploadState({ step: 'preview', data: r.data, meta: r.meta, fileName: file.name });
        } else {
          const e = result as ParseError;
          setUploadState({ step: 'error', errors: e.errors, fileName: file.name });
        }
      } catch (err) {
        setUploadState({
          step: 'error',
          errors: [err instanceof Error ? err.message : 'Erro desconhecido ao processar ficheiro.'],
          fileName: file.name,
        });
      }
    },
    [semantics],
  );

  // ── Handlers ──

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) processFile(file);
    },
    [processFile],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) processFile(file);
      if (fileRef.current) fileRef.current.value = '';
    },
    [processFile],
  );

  const handleApply = useCallback(async () => {
    if (uploadState.step !== 'preview') return;
    await setNikufraData(uploadState.data, uploadState.fileName, uploadState.meta);
    invalidateScheduleCache();
    setUploadState({ step: 'idle' });
  }, [uploadState, setNikufraData]);

  const handleClear = useCallback(() => {
    clearData();
    invalidateScheduleCache();
    setUploadState({ step: 'idle' });
  }, [clearData]);

  // ── Helpers ──

  function formatDateTime(iso: string): string {
    const d = new Date(iso);
    return (
      d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
      ' ' +
      d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })
    );
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

  function renderSummary(meta: LoadMeta) {
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

  function renderWarnings(warnings: string[]) {
    if (warnings.length === 0) return null;
    return (
      <div className="carregar-dados__warnings">
        {warnings.map((w, i) => (
          <div key={i} className="carregar-dados__warning">
            {w}
          </div>
        ))}
      </div>
    );
  }

  function renderErrors(errors: string[]) {
    return (
      <div className="carregar-dados__warnings">
        {errors.map((err, i) => (
          <div key={i} className="carregar-dados__warning carregar-dados__warning--error">
            {err}
          </div>
        ))}
      </div>
    );
  }

  // ── Render ──

  return (
    <div className={`carregar-dados${panelOpen ? ' carregar-dados--panel-open' : ''}`}>
      {/* Hidden file input */}
      <input
        ref={fileRef}
        type="file"
        accept=".xlsx,.xls"
        onChange={handleFileInput}
        style={{ display: 'none' }}
        data-testid="file-input"
      />

      {/* Header */}
      <div className="carregar-dados__header">
        <h2 className="carregar-dados__title">Definicoes do Sistema</h2>
        <p className="carregar-dados__desc">
          Importe o ISOP e configure os parametros do motor de planeamento.
        </p>
      </div>

      {/* Upload Section */}
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

        {/* Currently loaded */}
        {hasData && storedMeta && loadedAt && uploadState.step === 'idle' && (
          <div className="carregar-dados__loaded-info">
            <div className="carregar-dados__current-header">
              <FileSpreadsheet size={18} className="carregar-dados__current-icon" />
              <div className="carregar-dados__current-info">
                <span className="carregar-dados__current-file">{storedFileName}</span>
                <span className="carregar-dados__current-time">
                  Carregado: {formatDateTime(loadedAt)}
                </span>
              </div>
              <div className="carregar-dados__trust-badge-wrap">
                <span
                  className={`carregar-dados__trust-badge ${trustBadgeClass(storedMeta.trustScore)}`}
                >
                  {trustIcon(storedMeta.trustScore)}
                  {Math.round(storedMeta.trustScore * 100)}%
                </span>
              </div>
            </div>
            {renderSummary(storedMeta)}
            <div className="carregar-dados__actions">
              <button
                className="carregar-dados__btn carregar-dados__btn--primary"
                onClick={() => fileRef.current?.click()}
                data-testid="btn-new-isop"
              >
                Carregar Novo ISOP
              </button>
              <button
                className="carregar-dados__btn carregar-dados__btn--secondary"
                onClick={handleClear}
                data-testid="btn-clear"
              >
                <Trash2 size={14} />
                Limpar Dados
              </button>
            </div>
          </div>
        )}

        {/* Drop zone */}
        {(uploadState.step === 'idle' || uploadState.step === 'error') && !hasData && (
          <div
            className={`carregar-dados__dropzone ${dragActive ? 'carregar-dados__dropzone--active' : ''}`}
            onDrop={handleDrop}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onClick={() => fileRef.current?.click()}
            data-testid="dropzone"
          >
            <Upload size={28} className="carregar-dados__dropzone-icon" />
            <span className="carregar-dados__dropzone-text">Arraste o ISOP .xlsx aqui</span>
            <span className="carregar-dados__dropzone-hint">
              ou clique para selecionar ficheiro
            </span>
          </div>
        )}

        {/* Processing */}
        {uploadState.step === 'processing' && (
          <div className="carregar-dados__processing">
            <Loader size={18} className="carregar-dados__processing-spinner" />
            <span className="carregar-dados__processing-text">
              A processar {uploadState.fileName}...
            </span>
          </div>
        )}

        {/* Error */}
        {uploadState.step === 'error' && (
          <>
            <div className="carregar-dados__preview-header">
              <span className="carregar-dados__preview-title">Erros em {uploadState.fileName}</span>
              <span className="carregar-dados__trust-badge carregar-dados__trust-badge--red">
                <XCircle size={14} /> Erro
              </span>
            </div>
            {renderErrors(uploadState.errors)}
          </>
        )}

        {/* Preview */}
        {uploadState.step === 'preview' && (
          <div className="carregar-dados__preview">
            <div className="carregar-dados__preview-header">
              <span className="carregar-dados__preview-title">{uploadState.fileName}</span>
              <span
                className={`carregar-dados__trust-badge ${trustBadgeClass(uploadState.meta.trustScore)}`}
              >
                {trustIcon(uploadState.meta.trustScore)}
                {Math.round(uploadState.meta.trustScore * 100)}%
              </span>
            </div>
            {renderSummary(uploadState.meta)}
            {renderWarnings(uploadState.meta.warnings)}
            <div className="carregar-dados__actions">
              <button
                className="carregar-dados__btn carregar-dados__btn--primary"
                onClick={handleApply}
                data-testid="btn-apply"
              >
                Aplicar Dados
              </button>
              <button
                className="carregar-dados__btn carregar-dados__btn--secondary"
                onClick={() => setUploadState({ step: 'idle' })}
                data-testid="btn-cancel"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Semantics selector */}
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

      {/* §1 Turnos e Capacidade */}
      <ShiftsCapacitySection />

      {/* §2 Regras de Planeamento */}
      <PlanningRulesSection />

      {/* §3 Perfil de Optimizacao */}
      <OptimizationProfileSection />

      {/* §4 Capacidade de Operadores (M.O.) */}
      <MOStrategySection />

      {/* §5 Overflow e Routing */}
      <OverflowRoutingSection />

      {/* §6 MRP e Supply */}
      <MRPSupplySection />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  §1 — TURNOS E CAPACIDADE
// ═══════════════════════════════════════════════════════════════

function ShiftsCapacitySection() {
  const {
    shiftXStart,
    shiftChange,
    shiftYEnd,
    oee,
    thirdShiftDefault,
    setShifts,
    setOEE,
    setThirdShiftDefault,
  } = useSettingsStore();

  const config = useMemo(() => getEngineConfig(), [shiftXStart, shiftChange, shiftYEnd, oee]);

  return (
    <div className="carregar-dados__section" data-testid="section-shifts">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--shifts">
          <Clock size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Turnos e Capacidade</div>
          <div className="carregar-dados__section-subtitle">Grade temporal, OEE e 3.o turno</div>
        </div>
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Turno X inicio</label>
          <input
            type="time"
            value={shiftXStart}
            onChange={(e) => setShifts(e.target.value, shiftChange, shiftYEnd)}
            className="carregar-dados__mo-field-input carregar-dados__time-input"
            data-testid="shift-x-start"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Mudanca de turno</label>
          <input
            type="time"
            value={shiftChange}
            onChange={(e) => setShifts(shiftXStart, e.target.value, shiftYEnd)}
            className="carregar-dados__mo-field-input carregar-dados__time-input"
            data-testid="shift-change"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Turno Y fim</label>
          <input
            type="time"
            value={shiftYEnd === '24:00' ? '00:00' : shiftYEnd}
            onChange={(e) => {
              const v = e.target.value === '00:00' ? '24:00' : e.target.value;
              setShifts(shiftXStart, shiftChange, v);
            }}
            className="carregar-dados__mo-field-input carregar-dados__time-input"
            data-testid="shift-y-end"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">OEE (%)</label>
          <input
            type="number"
            min={50}
            max={90}
            step={1}
            value={Math.round(oee * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 50 && n <= 90) setOEE(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="oee-input"
          />
          <span className="carregar-dados__param-hint">50% — 90%</span>
        </div>
      </div>

      <div className="carregar-dados__param-preview" data-testid="capacity-preview">
        <span>DAY_CAP = {config.DAY_CAP} min</span>
        <span>OEE = {(config.OEE * 100).toFixed(0)}%</span>
      </div>

      <label className="carregar-dados__checkbox-row">
        <input
          type="checkbox"
          checked={thirdShiftDefault}
          onChange={(e) => setThirdShiftDefault(e.target.checked)}
          data-testid="third-shift-toggle"
        />
        <span className="carregar-dados__checkbox-label">3.o turno (Z) activo por defeito</span>
      </label>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  §2 — REGRAS DE PLANEAMENTO
// ═══════════════════════════════════════════════════════════════

const DISPATCH_OPTIONS: { value: DispatchRule; label: string; desc: string }[] = [
  {
    value: 'EDD',
    label: 'EDD — Earliest Due Date',
    desc: 'Prioriza prazos de entrega (recomendado OTD)',
  },
  {
    value: 'CR',
    label: 'CR — Critical Ratio',
    desc: 'Prioriza racio prazo / tempo de processamento',
  },
  { value: 'WSPT', label: 'WSPT — Weighted SPT', desc: 'Prioriza maior volume/tempo (throughput)' },
  { value: 'SPT', label: 'SPT — Shortest Processing Time', desc: 'Minimiza tempo total de fluxo' },
];

function PlanningRulesSection() {
  const {
    dispatchRule,
    bucketWindowDays,
    maxEddGapDays,
    defaultSetupHours,
    setDispatchRule,
    setBucketWindowDays,
    setMaxEddGapDays,
    setDefaultSetupHours,
  } = useSettingsStore();

  return (
    <div className="carregar-dados__section" data-testid="section-planning">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--planning">
          <ListOrdered size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Regras de Planeamento</div>
          <div className="carregar-dados__section-subtitle">
            Logica base do algoritmo de scheduling
          </div>
        </div>
      </div>

      <div className="carregar-dados__dispatch-options" data-testid="dispatch-options">
        {DISPATCH_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`carregar-dados__mo-option${dispatchRule === opt.value ? ' carregar-dados__mo-option--active' : ''}`}
            onClick={() => setDispatchRule(opt.value)}
            data-testid={`dispatch-${opt.value}`}
          >
            <span className="carregar-dados__mo-option-label">{opt.label}</span>
            <span className="carregar-dados__mo-option-desc">{opt.desc}</span>
          </button>
        ))}
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Janela agrupamento (dias)</label>
          <input
            type="number"
            min={2}
            max={10}
            value={bucketWindowDays}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 2 && n <= 10) setBucketWindowDays(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="bucket-window"
          />
          <span className="carregar-dados__param-hint">2 — 10 dias uteis</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Gap max. EDD (dias)</label>
          <input
            type="number"
            min={2}
            max={7}
            value={maxEddGapDays}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 2 && n <= 7) setMaxEddGapDays(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="edd-gap"
          />
          <span className="carregar-dados__param-hint">2 — 7 dias</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Setup padrao (h)</label>
          <input
            type="number"
            min={0.25}
            max={3.0}
            step={0.25}
            value={defaultSetupHours}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (!isNaN(n) && n >= 0.25 && n <= 3.0) setDefaultSetupHours(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="default-setup"
          />
          <span className="carregar-dados__param-hint">0.25 — 3.0 horas</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  §3 — PERFIL DE OPTIMIZACAO
// ═══════════════════════════════════════════════════════════════

const PROFILE_OPTIONS: { id: OptimizationProfile; label: string; desc: string }[] = [
  { id: 'balanced', label: 'Equilibrado', desc: 'Pesos balanceados para uso geral' },
  { id: 'otd', label: 'Entregar a Tempo', desc: 'Prioriza cumprimento de prazos' },
  { id: 'setup', label: 'Min. Setups', desc: 'Minimiza changeovers e tempo de setup' },
  { id: 'custom', label: 'Personalizado', desc: 'Ajuste fino de cada peso' },
];

const WEIGHT_DEFS: { key: string; label: string; max: number }[] = [
  { key: 'wTardiness', label: 'Atraso (tardiness)', max: 300 },
  { key: 'wSetupCount', label: 'N.o setups', max: 100 },
  { key: 'wSetupTime', label: 'Tempo setup', max: 10 },
  { key: 'wSetupBalance', label: 'Balanco turnos', max: 100 },
  { key: 'wChurn', label: 'Churn', max: 50 },
  { key: 'wOverflow', label: 'Overflow', max: 200 },
  { key: 'wBelowMinBatch', label: 'Lote minimo', max: 50 },
];

function OptimizationProfileSection() {
  const store = useSettingsStore();
  const {
    optimizationProfile,
    wTardiness,
    wSetupCount,
    wSetupTime,
    wSetupBalance,
    wChurn,
    wOverflow,
    wBelowMinBatch,
    setOptimizationProfile,
    setWeight,
  } = store;

  const weights: Record<string, number> = {
    wTardiness,
    wSetupCount,
    wSetupTime,
    wSetupBalance,
    wChurn,
    wOverflow,
    wBelowMinBatch,
  };

  return (
    <div className="carregar-dados__section" data-testid="section-optimization">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--weights">
          <SlidersHorizontal size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Perfil de Optimizacao</div>
          <div className="carregar-dados__section-subtitle">
            Pesos da funcao objectivo do scheduler
          </div>
        </div>
      </div>

      <div className="carregar-dados__profile-options" data-testid="profile-options">
        {PROFILE_OPTIONS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`carregar-dados__profile-btn${optimizationProfile === p.id ? ' carregar-dados__profile-btn--active' : ''}`}
            onClick={() => setOptimizationProfile(p.id)}
            data-testid={`profile-${p.id}`}
          >
            <span className="carregar-dados__profile-btn-label">{p.label}</span>
            <span className="carregar-dados__profile-btn-desc">{p.desc}</span>
          </button>
        ))}
      </div>

      {optimizationProfile === 'custom' && (
        <div className="carregar-dados__weights-grid" data-testid="weights-grid">
          {WEIGHT_DEFS.map((wd) => (
            <div key={wd.key} className="carregar-dados__weight-slider">
              <span className="carregar-dados__weight-label">{wd.label}</span>
              <input
                type="range"
                min={0}
                max={wd.max}
                step={wd.max > 50 ? 5 : wd.max > 10 ? 1 : 0.5}
                value={weights[wd.key]}
                onChange={(e) => setWeight(wd.key, parseFloat(e.target.value))}
                data-testid={`weight-${wd.key}`}
              />
              <span className="carregar-dados__weight-value">{weights[wd.key]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  §4 — CAPACIDADE DE OPERADORES (M.O.)
// ═══════════════════════════════════════════════════════════════

const MO_OPTIONS: { value: MOStrategy; label: string; desc: string }[] = [
  {
    value: 'nominal',
    label: 'Nominal (recomendado)',
    desc: 'Usa fixture para a 1.a semana, depois capacidade fixa.',
  },
  {
    value: 'cyclic',
    label: 'Ciclico',
    desc: 'Repete o padrao semanal da fixture (pode ter dias com <1 operador).',
  },
  {
    value: 'custom',
    label: 'Personalizado',
    desc: 'Define manualmente a capacidade por area.',
  },
];

function MOStrategySection() {
  const {
    moStrategy,
    moNominalPG1,
    moNominalPG2,
    moCustomPG1,
    moCustomPG2,
    setMOStrategy,
    setMONominal,
    setMOCustom,
  } = useSettingsStore();

  const showInputs = moStrategy === 'nominal' || moStrategy === 'custom';
  const pg1Val = moStrategy === 'custom' ? moCustomPG1 : moNominalPG1;
  const pg2Val = moStrategy === 'custom' ? moCustomPG2 : moNominalPG2;

  const handlePG1 = (v: string) => {
    const n = parseFloat(v);
    if (isNaN(n) || n < 0) return;
    if (moStrategy === 'custom') setMOCustom(n, moCustomPG2);
    else setMONominal(n, moNominalPG2);
  };
  const handlePG2 = (v: string) => {
    const n = parseFloat(v);
    if (isNaN(n) || n < 0) return;
    if (moStrategy === 'custom') setMOCustom(moCustomPG1, n);
    else setMONominal(moNominalPG1, n);
  };

  return (
    <div className="carregar-dados__section">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--operators">
          <Users size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Capacidade de Operadores (M.O.)</div>
          <div className="carregar-dados__section-subtitle">
            Estrategia para dias alem da fixture (horizonte &gt; 8 dias)
          </div>
        </div>
      </div>

      <div className="carregar-dados__mo-options" data-testid="mo-strategy-options">
        {MO_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`carregar-dados__mo-option${moStrategy === opt.value ? ' carregar-dados__mo-option--active' : ''}`}
            onClick={() => setMOStrategy(opt.value)}
            data-testid={`mo-option-${opt.value}`}
          >
            <span className="carregar-dados__mo-option-label">{opt.label}</span>
            <span className="carregar-dados__mo-option-desc">{opt.desc}</span>
          </button>
        ))}
      </div>

      {showInputs && (
        <div className="carregar-dados__mo-inputs" data-testid="mo-inputs">
          <div className="carregar-dados__mo-field">
            <label className="carregar-dados__mo-field-label">PG1 (operadores)</label>
            <input
              type="number"
              min={0}
              step={0.5}
              value={pg1Val}
              onChange={(e) => handlePG1(e.target.value)}
              className="carregar-dados__mo-field-input"
              data-testid="mo-input-pg1"
            />
          </div>
          <div className="carregar-dados__mo-field">
            <label className="carregar-dados__mo-field-label">PG2 (operadores)</label>
            <input
              type="number"
              min={0}
              step={0.5}
              value={pg2Val}
              onChange={(e) => handlePG2(e.target.value)}
              className="carregar-dados__mo-field-input"
              data-testid="mo-input-pg2"
            />
          </div>
          <div className="carregar-dados__mo-hint">
            {moStrategy === 'nominal'
              ? 'Capacidade constante aplicada a partir do dia 9 (apos a fixture).'
              : 'Capacidade personalizada para todos os dias alem da fixture.'}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  §5 — OVERFLOW E ROUTING
// ═══════════════════════════════════════════════════════════════

function OverflowRoutingSection() {
  const {
    altUtilThreshold,
    maxAutoMoves,
    maxOverflowIter,
    otdTolerance,
    loadBalanceThreshold,
    setAltUtilThreshold,
    setMaxAutoMoves,
    setMaxOverflowIter,
    setOTDTolerance,
    setLoadBalanceThreshold,
  } = useSettingsStore();

  return (
    <div className="carregar-dados__section" data-testid="section-overflow">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--routing">
          <GitBranch size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">Overflow e Routing</div>
          <div className="carregar-dados__section-subtitle">
            Redistribuicao automatica para maquinas alternativas
          </div>
        </div>
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Threshold sat. alt. (%)</label>
          <input
            type="number"
            min={80}
            max={100}
            step={1}
            value={Math.round(altUtilThreshold * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 80 && n <= 100) setAltUtilThreshold(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="alt-util-threshold"
          />
          <span className="carregar-dados__param-hint">80% — 100%</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Max auto-moves</label>
          <input
            type="number"
            min={4}
            max={32}
            value={maxAutoMoves}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 4 && n <= 32) setMaxAutoMoves(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="max-auto-moves"
          />
          <span className="carregar-dados__param-hint">4 — 32 operacoes</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Max iteracoes</label>
          <input
            type="number"
            min={1}
            max={5}
            value={maxOverflowIter}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 1 && n <= 5) setMaxOverflowIter(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="max-overflow-iter"
          />
          <span className="carregar-dados__param-hint">1 — 5 passagens</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Tolerancia OTD (%)</label>
          <input
            type="number"
            min={80}
            max={100}
            step={1}
            value={Math.round(otdTolerance * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 80 && n <= 100) setOTDTolerance(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="otd-tolerance"
          />
          <span className="carregar-dados__param-hint">80% — 100%</span>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Threshold rebal. (%)</label>
          <input
            type="number"
            min={5}
            max={30}
            step={1}
            value={Math.round(loadBalanceThreshold * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 5 && n <= 30) setLoadBalanceThreshold(n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="load-balance-threshold"
          />
          <span className="carregar-dados__param-hint">5% — 30%</span>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  §6 — MRP E SUPPLY
// ═══════════════════════════════════════════════════════════════

function MRPSupplySection() {
  const {
    serviceLevel,
    coverageThresholdDays,
    abcThresholdA,
    abcThresholdB,
    xyzThresholdX,
    xyzThresholdY,
    setServiceLevel,
    setCoverageThresholdDays,
    setABCThresholds,
    setXYZThresholds,
  } = useSettingsStore();

  return (
    <div className="carregar-dados__section" data-testid="section-mrp">
      <div className="carregar-dados__section-header">
        <div className="carregar-dados__section-icon carregar-dados__section-icon--mrp">
          <Package size={16} />
        </div>
        <div>
          <div className="carregar-dados__section-title">MRP e Supply</div>
          <div className="carregar-dados__section-subtitle">
            Safety stock, classificacao ABC/XYZ, alertas de supply
          </div>
        </div>
      </div>

      <div className="carregar-dados__params-grid">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Nivel de servico</label>
          <select
            value={serviceLevel}
            onChange={(e) => setServiceLevel(parseInt(e.target.value) as ServiceLevelOption)}
            className="carregar-dados__semantics-select"
            data-testid="service-level"
          >
            <option value={90}>90% (Z=1.28)</option>
            <option value={95}>95% (Z=1.645)</option>
            <option value={99}>99% (Z=2.33)</option>
          </select>
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">Cobertura min. (dias)</label>
          <input
            type="number"
            min={1}
            max={7}
            value={coverageThresholdDays}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 1 && n <= 7) setCoverageThresholdDays(n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="coverage-threshold"
          />
          <span className="carregar-dados__param-hint">1 — 7 dias</span>
        </div>
      </div>

      <div className="carregar-dados__params-grid carregar-dados__params-grid--4col">
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">ABC — A (%)</label>
          <input
            type="number"
            min={70}
            max={90}
            step={5}
            value={Math.round(abcThresholdA * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 70 && n <= 90) setABCThresholds(n / 100, abcThresholdB);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="abc-a"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">ABC — B (%)</label>
          <input
            type="number"
            min={90}
            max={98}
            step={1}
            value={Math.round(abcThresholdB * 100)}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (!isNaN(n) && n >= 90 && n <= 98) setABCThresholds(abcThresholdA, n / 100);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="abc-b"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">XYZ — X (CV)</label>
          <input
            type="number"
            min={0.3}
            max={0.7}
            step={0.1}
            value={xyzThresholdX}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (!isNaN(n) && n >= 0.3 && n <= 0.7) setXYZThresholds(n, xyzThresholdY);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="xyz-x"
          />
        </div>
        <div className="carregar-dados__param">
          <label className="carregar-dados__param-label">XYZ — Y (CV)</label>
          <input
            type="number"
            min={0.7}
            max={1.5}
            step={0.1}
            value={xyzThresholdY}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (!isNaN(n) && n >= 0.7 && n <= 1.5) setXYZThresholds(xyzThresholdX, n);
            }}
            className="carregar-dados__mo-field-input"
            data-testid="xyz-y"
          />
        </div>
      </div>
    </div>
  );
}

export default CarregarDados;
