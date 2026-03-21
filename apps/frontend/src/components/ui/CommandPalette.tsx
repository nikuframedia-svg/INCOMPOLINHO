// ═══════════════════════════════════════════════════════════
//  CommandPalette — ⌘K fuzzy search overlay
//
//  Glass modal, fuse.js fuzzy search.
//  Results: pages, machines, SKUs, actions.
// ═══════════════════════════════════════════════════════════

import Fuse from 'fuse.js';
import {
  Eye,
  CalendarRange,
  Boxes,
  Settings,
  Repeat,
  FlaskConical,
  Database,
  ShoppingCart,
  Clock,
  BarChart3,
  Search,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCommandPaletteOpen, useUIActions, useUIStore } from '@/stores/useUIStore';

interface PaletteItem {
  id: string;
  label: string;
  section: string;
  path: string;
  icon: LucideIcon;
  keywords?: string;
}

const PAGES: PaletteItem[] = [
  { id: 'console', label: 'Visão Geral', section: 'Páginas', path: '/console', icon: Eye, keywords: 'console dashboard overview' },
  { id: 'plan', label: 'Gantt', section: 'Páginas', path: '/plan', icon: BarChart3, keywords: 'gantt scheduling plano' },
  { id: 'replan', label: 'Replan', section: 'Páginas', path: '/plan/replan', icon: Repeat, keywords: 'replan replaneamento' },
  { id: 'whatif', label: 'What If', section: 'Páginas', path: '/plan/whatif', icon: FlaskConical, keywords: 'whatif cenário scenario simulação' },
  { id: 'data', label: 'Dados', section: 'Páginas', path: '/plan/data', icon: Database, keywords: 'upload isop dados data importar' },
  { id: 'mrp', label: 'Materiais', section: 'Páginas', path: '/mrp', icon: Boxes, keywords: 'mrp materiais stock inventário' },
  { id: 'orders', label: 'Encomendas', section: 'Páginas', path: '/mrp/orders', icon: ShoppingCart, keywords: 'encomendas orders pedidos clientes' },
  { id: 'ctp', label: 'CTP', section: 'Páginas', path: '/mrp/ctp', icon: Clock, keywords: 'ctp capable to promise prazo' },
  { id: 'settings', label: 'Settings', section: 'Páginas', path: '/settings', icon: Settings, keywords: 'configurações settings preferências' },
  { id: 'machines', label: 'Máquinas', section: 'Settings', path: '/settings/machines', icon: Settings, keywords: 'máquinas machines prensa PRM' },
  { id: 'shifts', label: 'Turnos', section: 'Settings', path: '/settings/shifts', icon: Settings, keywords: 'turnos shifts horário' },
  { id: 'setup-matrix', label: 'Setup Matrix', section: 'Settings', path: '/settings/setup-matrix', icon: Settings, keywords: 'setup matrix ferramenta' },
  { id: 'operators', label: 'Operadores', section: 'Settings', path: '/settings/operators', icon: Settings, keywords: 'operadores operators equipa' },
  { id: 'scheduling', label: 'Scheduling Config', section: 'Settings', path: '/settings/scheduling', icon: CalendarRange, keywords: 'scheduling atcs dispatch configuração' },
];

const fuse = new Fuse(PAGES, {
  keys: ['label', 'keywords', 'section'],
  threshold: 0.4,
  includeScore: true,
});

export function CommandPalette() {
  const open = useCommandPaletteOpen();
  const { closeCommandPalette } = useUIActions();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);

  const results = useMemo(() => {
    if (!query.trim()) return PAGES;
    return fuse.search(query).map((r) => r.item);
  }, [query]);

  // Reset on open
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Global ⌘K listener
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const state = useUIStore.getState();
        state.actions.toggleCommandPalette();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const selectItem = useCallback(
    (item: PaletteItem) => {
      closeCommandPalette();
      navigate(item.path);
    },
    [closeCommandPalette, navigate],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && results[selectedIdx]) {
        e.preventDefault();
        selectItem(results[selectedIdx]);
      } else if (e.key === 'Escape') {
        closeCommandPalette();
      }
    },
    [results, selectedIdx, selectItem, closeCommandPalette],
  );

  if (!open) return null;

  return (
    <div
      onClick={closeCommandPalette}
      onKeyDown={(e) => e.key === 'Escape' && closeCommandPalette()}
      role="presentation"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 950,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '15vh',
        background: 'rgba(6, 8, 13, 0.60)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
        role="dialog"
        aria-label="Command palette"
        style={{
          width: '100%',
          maxWidth: 540,
          background: 'var(--bg-surface-solid)',
          border: '1px solid var(--glass-border)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-overlay)',
          overflow: 'hidden',
          animation: 'fadeIn 0.15s ease-out',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '12px 16px',
            borderBottom: '1px solid var(--glass-border)',
          }}
        >
          <Search size={16} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIdx(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Pesquisar páginas, máquinas, SKUs..."
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontSize: 14,
              fontFamily: 'inherit',
            }}
          />
          <kbd
            style={{
              fontSize: 12,
              fontFamily: 'var(--font-mono)',
              padding: '2px 6px',
              background: 'rgba(255,255,255,0.06)',
              borderRadius: 4,
              color: 'var(--text-ghost)',
            }}
          >
            ESC
          </kbd>
        </div>

        <div style={{ maxHeight: 360, overflowY: 'auto', padding: '4px 0' }}>
          {results.length === 0 && (
            <div
              style={{
                padding: '24px 16px',
                textAlign: 'center',
                color: 'var(--text-muted)',
                fontSize: 13,
              }}
            >
              Sem resultados
            </div>
          )}
          {results.map((item, idx) => {
            const Icon = item.icon;
            const isSelected = idx === selectedIdx;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => selectItem(item)}
                onMouseEnter={() => setSelectedIdx(idx)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  width: '100%',
                  padding: '8px 16px',
                  background: isSelected ? 'rgba(129, 140, 248, 0.08)' : 'transparent',
                  border: 'none',
                  color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontSize: 13,
                  fontFamily: 'inherit',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'background 0.1s',
                }}
              >
                <Icon size={16} style={{ opacity: 0.6, flexShrink: 0 }} />
                <span style={{ flex: 1 }}>{item.label}</span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{item.section}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
