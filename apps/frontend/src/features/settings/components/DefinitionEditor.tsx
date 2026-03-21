/**
 * DefinitionEditor — Concept definition with formula, impact preview, and version rollback.
 */

import { Parser } from 'expr-eval';
import { useEffect, useRef, useState } from 'react';
import type { ConceptDefinition } from '@/stores/settings-types';
import './FormulaEditor.css';

export type { ConceptDefinition } from '@/stores/settings-types';

interface DefinitionEditorProps {
  definition: ConceptDefinition;
  onChange: (updated: ConceptDefinition) => void;
  impactPreview: { matching: number; total: number } | null;
}

export function DefinitionEditor({ definition, onChange, impactPreview }: DefinitionEditorProps) {
  const [parseError, setParseError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try {
      const parser = new Parser();
      parser.parse(definition.expression);
      setParseError(null);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Expressão inválida');
    }
  }, [definition.expression]);

  const handleChange = (expression: string) => {
    const prev = {
      v: definition.version,
      ts: new Date().toISOString(),
      expression: definition.expression,
    };
    onChange({
      ...definition,
      expression,
      version: definition.version + 1,
      versions: [...definition.versions, prev],
    });
  };

  const insertVar = (varName: string) => {
    const ta = textareaRef.current;
    if (!ta) {
      handleChange(definition.expression + varName);
      return;
    }
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const before = definition.expression.slice(0, start);
    const after = definition.expression.slice(end);
    handleChange(before + varName + after);
    requestAnimationFrame(() => {
      ta.focus();
      ta.selectionStart = ta.selectionEnd = start + varName.length;
    });
  };

  const rollback = () => {
    if (definition.versions.length === 0) return;
    const prev = definition.versions[definition.versions.length - 1];
    onChange({
      ...definition,
      expression: prev.expression,
      version: definition.version + 1,
      versions: definition.versions.slice(0, -1),
    });
  };

  const validClass = parseError ? 'formula-editor__input--invalid' : 'formula-editor__input--valid';

  return (
    <div className="definition-editor">
      <div className="definition-editor__question">{definition.question}</div>

      <textarea
        ref={textareaRef}
        className={`formula-editor__input ${validClass}`}
        value={definition.expression}
        onChange={(e) => handleChange(e.target.value)}
        rows={2}
        spellCheck={false}
      />

      {parseError && <div className="formula-editor__error">{parseError}</div>}

      <div className="formula-editor__vars">
        {definition.variables.map((v) => (
          <button key={v} className="formula-editor__var-chip" onClick={() => insertVar(v)}>
            {v}
          </button>
        ))}
      </div>

      {impactPreview && !parseError && (
        <div className="definition-editor__impact">
          Com esta definição, <strong>{impactPreview.matching}</strong> de {impactPreview.total}{' '}
          operações seriam classificadas como <strong>{definition.label}</strong>
        </div>
      )}

      <div className="definition-editor__version-row">
        <span>
          v{definition.version} · {definition.versions.length} versões anteriores
        </span>
        {definition.versions.length > 0 && (
          <button
            className="constraint-toggles__param-select"
            style={{ cursor: 'pointer', fontSize: 12, padding: '2px 8px' }}
            onClick={rollback}
          >
            Reverter
          </button>
        )}
      </div>
    </div>
  );
}
