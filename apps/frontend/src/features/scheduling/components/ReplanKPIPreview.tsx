/**
 * ReplanKPIPreview — Before vs after KPI comparison when a replan is executed.
 *
 * Shows OTD, Setups, Tardiness, Overflows with delta indicators.
 */

import { Check, X } from 'lucide-react';
import './ReplanKPIPreview.css';
import { C } from '@/theme/color-bridge';

interface KPISnapshot {
  otd: number;
  setupMin: number;
  tardiness: number;
  overflows: number;
}

interface ReplanKPIPreviewProps {
  before: KPISnapshot;
  after: KPISnapshot;
  movesCount: number;
  onApply: () => void;
  onCancel: () => void;
}

function deltaColor(before: number, after: number, lowerIsBetter: boolean): string {
  const diff = after - before;
  if (Math.abs(diff) < 0.1) return C.t3;
  const worse = lowerIsBetter ? diff > 0 : diff < 0;
  return worse ? C.rd : C.ac;
}

function formatDelta(
  before: number,
  after: number,
  suffix: string,
  _lowerIsBetter: boolean,
): string {
  const diff = after - before;
  const sign = diff > 0 ? '+' : '';
  return `${sign}${diff.toFixed(1)}${suffix}`;
}

interface KPIRowProps {
  label: string;
  before: string;
  after: string;
  delta: string;
  color: string;
}

function KPIRow({ label, before, after, delta, color }: KPIRowProps) {
  return (
    <>
      <div className="kpi-preview__cell kpi-preview__cell--label">{label}</div>
      <div className="kpi-preview__cell">{before}</div>
      <div className="kpi-preview__cell" style={{ color }}>
        {after}
      </div>
      <div className="kpi-preview__cell kpi-preview__cell--delta" style={{ color }}>
        {delta}
      </div>
    </>
  );
}

export function ReplanKPIPreview({
  before,
  after,
  movesCount,
  onApply,
  onCancel,
}: ReplanKPIPreviewProps) {
  return (
    <div className="kpi-preview">
      <div className="kpi-preview__header">
        <span className="kpi-preview__title">Preview — Antes vs Depois</span>
        <span className="kpi-preview__moves">{movesCount} movimentos</span>
      </div>

      <div className="kpi-preview__grid">
        <div className="kpi-preview__cell kpi-preview__cell--header">Métrica</div>
        <div className="kpi-preview__cell kpi-preview__cell--header">Antes</div>
        <div className="kpi-preview__cell kpi-preview__cell--header">Depois</div>
        <div className="kpi-preview__cell kpi-preview__cell--header">Delta</div>

        <KPIRow
          label="OTD-D"
          before={`${before.otd.toFixed(1)}%`}
          after={`${after.otd.toFixed(1)}%`}
          delta={formatDelta(before.otd, after.otd, '%', false)}
          color={deltaColor(before.otd, after.otd, false)}
        />
        <KPIRow
          label="Setups"
          before={`${(before.setupMin / 60).toFixed(1)}h`}
          after={`${(after.setupMin / 60).toFixed(1)}h`}
          delta={formatDelta(before.setupMin / 60, after.setupMin / 60, 'h', true)}
          color={deltaColor(before.setupMin, after.setupMin, true)}
        />
        <KPIRow
          label="Tardiness"
          before={`${before.tardiness}d`}
          after={`${after.tardiness}d`}
          delta={formatDelta(before.tardiness, after.tardiness, 'd', true)}
          color={deltaColor(before.tardiness, after.tardiness, true)}
        />
        <KPIRow
          label="Overflows"
          before={`${before.overflows}`}
          after={`${after.overflows}`}
          delta={formatDelta(before.overflows, after.overflows, '', true)}
          color={deltaColor(before.overflows, after.overflows, true)}
        />
      </div>

      <div className="kpi-preview__actions">
        <button className="kpi-preview__btn kpi-preview__btn--apply" onClick={onApply}>
          <Check
            size={10}
            strokeWidth={2}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }}
          />
          Aplicar Replan
        </button>
        <button className="kpi-preview__btn kpi-preview__btn--cancel" onClick={onCancel}>
          <X
            size={10}
            strokeWidth={2}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }}
          />
          Cancelar
        </button>
      </div>
    </div>
  );
}
