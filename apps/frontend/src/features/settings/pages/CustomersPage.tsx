/**
 * CustomersPage — Customer tiers and delay multipliers.
 * Route: /settings/customers
 *
 * Tiers persist in useSettingsStore.clientTiers (affects alert priority
 * and delay cost in DeliveryRiskPanel). Multiplier and SLA are local-only
 * for now (future: persist to master data store).
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useSettingsStore } from '@/stores/useSettingsStore';

interface CustomerRow {
  code: string;
  name: string;
  tier: number;
  multiplier: number;
  sla: string;
  orderCount: number;
}

const TIER_LABELS: Record<number, string> = {
  1: 'Critico',
  2: 'Alto',
  3: 'Normal',
  4: 'Baixo',
  5: 'Minimo',
};

function defaultTier(name: string): { tier: number; multiplier: number } {
  const n = name.toLowerCase();
  if (n.includes('faurecia') || n.includes('forvia')) return { tier: 1, multiplier: 10 };
  if (n.includes('continental') || n.includes('bosch')) return { tier: 2, multiplier: 7 };
  if (!name || name === 'Sem cliente') return { tier: 5, multiplier: 1 };
  return { tier: 3, multiplier: 3 };
}

function tierColor(tier: number): string {
  if (tier <= 1) return 'var(--semantic-red)';
  if (tier <= 2) return 'var(--semantic-amber)';
  return 'var(--accent)';
}

function multiplierColor(m: number): string {
  if (m >= 8) return 'var(--semantic-red)';
  if (m >= 3) return 'var(--semantic-amber)';
  return 'var(--accent)';
}

export function CustomersPage() {
  const { engine, loading, error } = useScheduleData();
  const storedTiers = useSettingsStore((s) => s.clientTiers);
  const setClientTier = useSettingsStore((s) => s.actions.setClientTier);

  const initialCustomers = useMemo(() => {
    if (!engine) return [];
    const map = new Map<string, { name: string; count: number }>();
    for (const op of engine.ops) {
      const code = op.cl || '__none__';
      const existing = map.get(code);
      if (existing) {
        existing.count++;
      } else {
        map.set(code, { name: op.clNm || 'Sem cliente', count: 1 });
      }
    }
    const rows: CustomerRow[] = [];
    for (const [code, info] of map) {
      const dt = defaultTier(info.name);
      const realCode = code === '__none__' ? '-' : code;
      const persistedTier = storedTiers[realCode];
      rows.push({
        code: realCode,
        name: info.name,
        tier: persistedTier ?? dt.tier,
        multiplier: dt.multiplier,
        sla: '',
        orderCount: info.count,
      });
    }
    return rows.sort((a, b) => a.tier - b.tier || a.name.localeCompare(b.name));
  }, [engine, storedTiers]);

  const [customers, setCustomers] = useState<CustomerRow[]>([]);

  // Sync when engine loads or storedTiers changes
  useEffect(() => {
    if (initialCustomers.length > 0) setCustomers(initialCustomers);
  }, [initialCustomers]);

  const handleTierChange = (code: string, tier: number) => {
    setCustomers((prev) => prev.map((c) => (c.code === code ? { ...c, tier } : c)));
    setClientTier(code, tier);
  };

  const updateMultiplier = (code: string, multiplier: number) => {
    setCustomers((prev) => prev.map((c) => (c.code === code ? { ...c, multiplier } : c)));
  };
  const updateSla = (code: string, sla: string) => {
    setCustomers((prev) => prev.map((c) => (c.code === code ? { ...c, sla } : c)));
  };

  if (loading)
    return (
      <div style={{ padding: 32 }}>
        <SkeletonTable rows={8} cols={5} />
      </div>
    );
  if (error || !engine) {
    return (
      <div style={{ padding: 32 }}>
        <Link
          to="/settings"
          style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
        >
          ← Settings
        </Link>
        <EmptyState icon="error" title="Sem dados" description={error || 'Importe ISOP.'} />
      </div>
    );
  }

  const editedCount = Object.keys(storedTiers).length;

  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Link to="/settings" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
        ← Settings
      </Link>
      <h2
        style={{
          color: 'var(--text-primary)',
          fontSize: 'var(--text-h3)',
          fontWeight: 600,
          margin: 0,
        }}
      >
        Clientes e Prioridades
      </h2>

      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {customers.length} clientes · Tier afecta prioridade de alertas e custo de atraso
        {editedCount > 0 && (
          <span style={{ marginLeft: 8, color: 'var(--accent)', fontWeight: 600 }}>
            · {editedCount} editado{editedCount > 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="setup-matrix">
          <thead>
            <tr>
              <th className="setup-matrix__header">Código</th>
              <th className="setup-matrix__header">Nome</th>
              <th className="setup-matrix__header" style={{ textAlign: 'center' }}>
                Encomendas
              </th>
              <th className="setup-matrix__header" style={{ textAlign: 'center' }}>
                Tier
              </th>
              <th className="setup-matrix__header" style={{ textAlign: 'center' }}>
                Multiplicador
              </th>
              <th className="setup-matrix__header">SLA</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.code}>
                <td
                  className="setup-matrix__cell"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 500 }}
                >
                  {c.code}
                </td>
                <td
                  className="setup-matrix__cell"
                  style={{ fontSize: 12, color: 'var(--text-primary)' }}
                >
                  {c.name}
                </td>
                <td
                  className="setup-matrix__cell"
                  style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: 12 }}
                >
                  {c.orderCount}
                </td>
                <td className="setup-matrix__cell" style={{ textAlign: 'center' }}>
                  <select
                    value={c.tier}
                    onChange={(e) => handleTierChange(c.code, Number(e.target.value))}
                    className="constraint-toggles__param-select"
                    style={{
                      fontSize: 12,
                      width: 90,
                      textAlign: 'center',
                      color: tierColor(c.tier),
                      borderLeft: storedTiers[c.code] != null
                        ? '2px solid var(--accent)'
                        : undefined,
                    }}
                  >
                    {[1, 2, 3, 4, 5].map((t) => (
                      <option key={t} value={t}>
                        {t} — {TIER_LABELS[t]}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="setup-matrix__cell" style={{ textAlign: 'center' }}>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={c.multiplier}
                    onChange={(e) =>
                      updateMultiplier(c.code, Math.max(1, Number(e.target.value) || 1))
                    }
                    style={{
                      width: 50,
                      textAlign: 'center',
                      fontSize: 12,
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      color: multiplierColor(c.multiplier),
                      background: 'transparent',
                      border: '1px solid var(--border-default)',
                      borderRadius: 3,
                      padding: '2px 4px',
                    }}
                  />
                </td>
                <td className="setup-matrix__cell">
                  <input
                    type="text"
                    value={c.sla}
                    onChange={(e) => updateSla(c.code, e.target.value)}
                    placeholder="—"
                    style={{
                      fontSize: 12,
                      width: 100,
                      background: 'transparent',
                      border: '1px solid var(--border-default)',
                      borderRadius: 3,
                      padding: '2px 6px',
                      color: 'var(--text-primary)',
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
