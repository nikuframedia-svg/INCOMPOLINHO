/**
 * FormulaEditor — Editable formula with validation, variable chips, and histogram preview.
 */

import { Parser } from 'expr-eval';
import { useEffect, useRef, useState } from 'react';
import type { FormulaConfig } from '@/stores/settings-types';
import './FormulaEditor.css';

export type { FormulaConfig } from '@/stores/settings-types';

interface FormulaEditorProps {
  formula: FormulaConfig;
  onChange: (updated: FormulaConfig) => void;
  previewData: number[] | null;
}

interface HistogramBucket {
  label: string;
  count: number;
}

function bucketize(values: number[], n = 5): HistogramBucket[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const step = (max - min) / n || 1;
  const buckets = Array.from({ length: n }, (_, i) => ({
    label: `${(min + i * step).toFixed(1)}`,
    count: 0,
  }));
  for (const v of values) {
    const idx = Math.min(Math.floor((v - min) / step), n - 1);
    buckets[idx].count++;
  }
  return buckets;
}

export function FormulaEditor({ formula, onChange, previewData }: FormulaEditorProps) {
  const [parseError, setParseError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try {
      const parser = new Parser();
      parser.parse(formula.expression);
      setParseError(null);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Expressão inválida');
    }
  }, [formula.expression]);

  const handleChange = (expression: string) => {
    const prev = {
      v: formula.version,
      ts: new Date().toISOString(),
      expression: formula.expression,
    };
    onChange({
      ...formula,
      expression,
      version: formula.version + 1,
      versions: [...formula.versions, prev],
    });
  };

  const insertVar = (varName: string) => {
    const ta = textareaRef.current;
    if (!ta) {
      handleChange(formula.expression + varName);
      return;
    }
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const before = formula.expression.slice(0, start);
    const after = formula.expression.slice(end);
    handleChange(before + varName + after);
    requestAnimationFrame(() => {
      ta.focus();
      ta.selectionStart = ta.selectionEnd = start + varName.length;
    });
  };

  const validClass = parseError ? 'formula-editor__input--invalid' : 'formula-editor__input--valid';
  const buckets = previewData ? bucketize(previewData) : [];
  const maxCount = Math.max(...buckets.map((b) => b.count), 1);

  return (
    <div className="formula-editor">
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
          {formula.label}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
          {formula.description}
        </div>
      </div>

      <textarea
        ref={textareaRef}
        className={`formula-editor__input ${validClass}`}
        value={formula.expression}
        onChange={(e) => handleChange(e.target.value)}
        rows={2}
        spellCheck={false}
      />

      {parseError && <div className="formula-editor__error">{parseError}</div>}

      <div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
          Variáveis disponíveis:
        </div>
        <div className="formula-editor__vars">
          {formula.variables.map((v) => (
            <button key={v} className="formula-editor__var-chip" onClick={() => insertVar(v)}>
              {v}
            </button>
          ))}
        </div>
      </div>

      {buckets.length > 0 && (
        <div>
          <div className="formula-editor__preview">
            Preview: {previewData?.length ?? 0} operações avaliadas
          </div>
          <div className="formula-editor__histogram">
            {buckets.map((b, i) => (
              <div
                key={i}
                className="formula-editor__histogram-bar"
                style={{ height: `${(b.count / maxCount) * 100}%` }}
                title={`${b.label}: ${b.count} ops`}
              />
            ))}
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 12,
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              marginTop: 2,
            }}
          >
            <span>{buckets[0]?.label}</span>
            <span>{buckets[buckets.length - 1]?.label}</span>
          </div>
        </div>
      )}

      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        v{formula.version} · {formula.versions.length} versões anteriores
      </div>
    </div>
  );
}
