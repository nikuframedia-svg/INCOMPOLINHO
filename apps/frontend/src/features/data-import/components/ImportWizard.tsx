/**
 * ImportWizard — 3-step modal shown after first ISOP import.
 * Step 1: Confirm detected stats. Step 2: Top client priority.
 * Step 3: Select scheduling strategy. Zero navigation, 2 minutes.
 */

import { Modal } from 'antd';
import { useCallback, useState } from 'react';
import { POLICY_LABELS, useConfigPreview } from '@/features/settings/useConfigPreview';
import { useToastStore } from '@/stores/useToastStore';
import type { IsopPresets, PolicyId } from '../utils/generate-presets';
import './ImportWizard.css';

interface ImportWizardProps {
  open: boolean;
  presets: IsopPresets | null;
  onClose: () => void;
}

type Step = 1 | 2 | 3;

const STRATEGY_OPTIONS: PolicyId[] = ['incompol_standard', 'balanced', 'max_otd', 'min_setups'];

function StepDots({ current }: { current: Step }) {
  return (
    <div className="import-wizard__dots">
      {([1, 2, 3] as const).map((s) => (
        <div
          key={s}
          className={`import-wizard__dot${s === current ? ' import-wizard__dot--active' : ''}${s < current ? ' import-wizard__dot--done' : ''}`}
        />
      ))}
    </div>
  );
}

export function ImportWizard({ open, presets, onClose }: ImportWizardProps) {
  const [step, setStep] = useState<Step>(1);
  const [selectedPolicy, setSelectedPolicy] = useState<PolicyId>('incompol_standard');
  const [_tierChoice, setTierChoice] = useState<'top' | 'equal'>('top');
  const setPolicy = useConfigPreview((s) => s.setPolicy);
  const addToast = useToastStore((s) => s.actions.addToast);

  const handleClose = useCallback(() => {
    setStep(1);
    setSelectedPolicy('incompol_standard');
    setTierChoice('top'); // reset for next open
    onClose();
  }, [onClose]);

  const handleFinish = useCallback(() => {
    setPolicy(selectedPolicy);
    addToast('Configuracao aplicada com sucesso!', 'success');
    handleClose();
  }, [selectedPolicy, setPolicy, addToast, handleClose]);

  if (!presets) return null;

  const { stats, topClient, bottleneckMachine } = presets;

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      footer={null}
      width={520}
      title={`Configuracao Rapida — Passo ${step}/3`}
      destroyOnClose
    >
      <StepDots current={step} />

      {step === 1 && (
        <div className="import-wizard__step">
          <p className="import-wizard__text">Detectamos os seguintes dados no ISOP:</p>
          <div className="import-wizard__stat-grid">
            <div className="import-wizard__stat">
              <span className="import-wizard__stat-value">{stats.machines}</span>
              <span className="import-wizard__stat-label">Máquinas</span>
            </div>
            <div className="import-wizard__stat">
              <span className="import-wizard__stat-value">{stats.skus}</span>
              <span className="import-wizard__stat-label">SKUs</span>
            </div>
            <div className="import-wizard__stat">
              <span className="import-wizard__stat-value">{stats.clients}</span>
              <span className="import-wizard__stat-label">Clientes</span>
            </div>
            <div className="import-wizard__stat">
              <span className="import-wizard__stat-value">{stats.days}</span>
              <span className="import-wizard__stat-label">Dias</span>
            </div>
          </div>
          {bottleneckMachine.id && (
            <p className="import-wizard__hint">
              Máquina mais carregada: <strong>{bottleneckMachine.id}</strong> (
              {bottleneckMachine.orderCount} operações)
            </p>
          )}
          <div className="import-wizard__actions">
            <button
              type="button"
              className="import-wizard__btn import-wizard__btn--secondary"
              onClick={handleClose}
            >
              Ajustar manualmente
            </button>
            <button
              type="button"
              className="import-wizard__btn import-wizard__btn--primary"
              onClick={() => setStep(2)}
            >
              Continuar
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="import-wizard__step">
          <p className="import-wizard__text">Cliente com mais encomendas:</p>
          <div className="import-wizard__client-badge">
            <span className="import-wizard__client-name">
              {topClient.name || topClient.id}
            </span>
            <span className="import-wizard__client-count">
              {topClient.orderCount} operações
            </span>
          </div>
          <p className="import-wizard__text">Definir como prioridade maxima?</p>
          <div className="import-wizard__actions">
            <button
              type="button"
              className="import-wizard__btn import-wizard__btn--secondary"
              onClick={() => {
                setTierChoice('equal');
                setStep(3);
              }}
            >
              Todos iguais
            </button>
            <button
              type="button"
              className="import-wizard__btn import-wizard__btn--primary"
              onClick={() => {
                setTierChoice('top');
                setStep(3);
              }}
            >
              Sim — Tier 1
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="import-wizard__step">
          <p className="import-wizard__text">Estrategia recomendada:</p>
          <div className="import-wizard__policy-cards">
            {STRATEGY_OPTIONS.map((id) => {
              const p = POLICY_LABELS[id];
              return (
                <button
                  key={id}
                  type="button"
                  className={`import-wizard__policy-card${selectedPolicy === id ? ' import-wizard__policy-card--active' : ''}`}
                  onClick={() => setSelectedPolicy(id)}
                  data-testid={`wizard-policy-${id}`}
                >
                  <span className="import-wizard__policy-name">{p.name}</span>
                  <span className="import-wizard__policy-desc">{p.desc}</span>
                </button>
              );
            })}
          </div>
          <div className="import-wizard__actions">
            <button
              type="button"
              className="import-wizard__btn import-wizard__btn--secondary"
              onClick={handleClose}
            >
              Personalizar depois
            </button>
            <button
              type="button"
              className="import-wizard__btn import-wizard__btn--primary"
              onClick={handleFinish}
            >
              Aplicar
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
