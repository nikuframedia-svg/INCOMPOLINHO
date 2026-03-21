/**
 * FocusStrip — Persistent bottom bar showing active context.
 *
 * Displays selected machine, day, scenario, tool as removable pills.
 * Visible on all pages for context continuity.
 * Also shows Cmd+K shortcut hint.
 */

import { X } from 'lucide-react';
import type { FocusContext } from '../../stores/useUIStore';
import { useUIStore } from '../../stores/useUIStore';
import './FocusStrip.css';

export function FocusStrip() {
  const focus = useUIStore((s) => s.focus);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const pills: Array<{ key: keyof FocusContext; label: string; value: string }> = [];

  if (focus.machine) pills.push({ key: 'machine', label: 'Máquina', value: focus.machine });
  if (focus.day) pills.push({ key: 'day', label: 'Dia', value: focus.day });
  if (focus.toolId) pills.push({ key: 'toolId', label: 'Ferramenta', value: focus.toolId });
  if (focus.scenario) pills.push({ key: 'scenario', label: 'Cenario', value: focus.scenario });

  const isEmpty = pills.length === 0;

  return (
    <div className={`focus-strip ${isEmpty ? 'focus-strip--empty' : ''}`} data-testid="focus-strip">
      <span className="focus-strip__label">Contexto</span>

      <div className="focus-strip__pills">
        {pills.map((p) => (
          <span key={p.key} className="focus-strip__pill">
            <span className="focus-strip__pill-key">{p.label}:</span>
            <span className="focus-strip__pill-value">{p.value}</span>
            <span
              className="focus-strip__pill-close"
              onClick={() => setFocus({ [p.key]: null })}
              data-testid={`focus-strip-remove-${p.key}`}
            >
              <X size={10} />
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
