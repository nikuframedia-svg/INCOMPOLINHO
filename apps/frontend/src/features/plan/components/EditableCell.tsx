/**
 * EditableCell — Inline editable table cell.
 *
 * Click to edit, Enter/blur to save, Esc to cancel.
 * Shows accent border when value has been overridden.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import './EditableCell.css';
import { C } from '@/theme/color-bridge';

interface EditableCellProps {
  value: string | number;
  type: 'text' | 'number' | 'select';
  options?: { value: string; label: string }[];
  onSave: (value: string | number) => void;
  isOverridden?: boolean;
  suffix?: string;
}

export function EditableCell({
  value,
  type,
  options,
  onSave,
  isOverridden,
  suffix,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(String(value));
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [editing, value]);

  const save = useCallback(() => {
    setEditing(false);
    const newVal = type === 'number' ? Number(draft) : draft;
    if (String(newVal) !== String(value)) onSave(newVal);
  }, [draft, value, type, onSave]);

  const cancel = useCallback(() => {
    setEditing(false);
    setDraft(String(value));
  }, [value]);

  if (editing) {
    if (type === 'select' && options) {
      return (
        <select
          ref={inputRef as React.RefObject<HTMLSelectElement>}
          className="editable-cell__select"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
          }}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === 'Escape') cancel();
          }}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        className="editable-cell__input"
        type={type}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter') save();
          if (e.key === 'Escape') cancel();
        }}
        step={type === 'number' ? 'any' : undefined}
      />
    );
  }

  return (
    <span
      className={`editable-cell${isOverridden ? ' editable-cell--overridden' : ''}`}
      onClick={() => setEditing(true)}
      style={isOverridden ? { borderColor: `${C.ac}66` } : undefined}
      title="Clique para editar"
    >
      {value}
      {suffix ? ` ${suffix}` : ''}
    </span>
  );
}
