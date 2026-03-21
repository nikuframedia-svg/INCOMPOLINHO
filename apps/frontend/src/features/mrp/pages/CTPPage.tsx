/**
 * CTPPage — Capable-to-Promise standalone page with 3-scenario simulation.
 * Route: /mrp/ctp
 */

import { AlertTriangle } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { C } from '@/lib/engine';
import { useDataStore } from '@/stores/useDataStore';
import { CTPChart } from '../components/CTPChart';
import { CTPForm } from '../components/CTPForm';
import { CTPScenarioCard } from '../components/CTPScenarioCard';
import { KCard } from '../components/KCard';
import type { CTPCommitment } from '../utils/ctp-compute';
import { computeConfidenceInterval, computeCTPScenarios } from '../utils/ctp-compute';
import { fmtQty, mono } from '../utils/mrp-helpers';

function TrustWarning({ score }: { score: number }) {
  if (score >= 0.7) return null;
  return (
    <div
      style={{
        padding: '6px 12px',
        background: `${C.yl}14`,
        border: `1px solid ${C.yl}30`,
        borderRadius: 4,
        fontSize: 12,
        color: C.yl,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 12,
      }}
    >
      <AlertTriangle size={12} />
      TrustIndex baixo ({(score * 100).toFixed(0)}%) — resultados CTP com menor fiabilidade
    </div>
  );
}

function CommitmentRow({ c }: { c: CTPCommitment }) {
  return (
    <tr>
      <td style={{ ...mono, fontSize: 12, color: C.t1 }}>{c.sku}</td>
      <td style={{ fontSize: 12, color: C.t2 }}>{c.customer ?? '-'}</td>
      <td style={{ ...mono, fontSize: 12, color: C.t1, textAlign: 'right' }}>
        {fmtQty(c.quantity)}
      </td>
      <td style={{ ...mono, fontSize: 12, color: C.ac }}>{c.promisedDate}</td>
      <td style={{ ...mono, fontSize: 12, color: C.t2 }}>{c.machine}</td>
      <td style={{ ...mono, fontSize: 12, color: C.t3 }}>{c.confidencePercent}%</td>
    </tr>
  );
}

export function CTPPage() {
  const { engine, mrp, loading, error } = useScheduleData();
  const trustScore = useDataStore((s) => s.meta?.trustScore) ?? 0.5;

  const [sku, setSku] = useState('');
  const [qty, setQty] = useState(5000);
  const [targetDay, setTargetDay] = useState(0);
  const [customer, setCustomer] = useState('');
  const [commitments, setCommitments] = useState<CTPCommitment[]>([]);
  const [ran, setRan] = useState(false);

  const scenarios = useMemo(() => {
    if (!ran || !sku || !mrp || !engine) return [];
    return computeCTPScenarios(sku, qty, targetDay, mrp, engine);
  }, [ran, sku, qty, targetDay, mrp, engine]);

  const bestScenario = scenarios.find((s) => s.result.feasible) ?? scenarios[0] ?? null;

  const confidenceMap = useMemo(() => {
    if (!engine) return new Map<string, ReturnType<typeof computeConfidenceInterval>>();
    const map = new Map<string, ReturnType<typeof computeConfidenceInterval>>();
    for (const s of scenarios) {
      map.set(s.id + s.machine, computeConfidenceInterval(s.result, trustScore, engine));
    }
    return map;
  }, [scenarios, trustScore, engine]);

  const handleRun = () => {
    if (sku && qty > 0) setRan(true);
  };

  const handleCommit = (s: (typeof scenarios)[0]) => {
    if (!engine || s.result.earliestFeasibleDay == null) return;
    const op = engine.ops.find((o) => o.sku === sku);
    const ci = confidenceMap.get(s.id + s.machine);
    const c: CTPCommitment = {
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      sku,
      skuName: op?.nm ?? sku,
      customer: customer || null,
      quantity: qty,
      promisedDay: s.result.earliestFeasibleDay,
      promisedDate:
        engine.dates[s.result.earliestFeasibleDay] ?? `D${s.result.earliestFeasibleDay}`,
      machine: s.machine,
      confidence: s.result.confidence,
      confidencePercent: ci?.confidencePercent ?? 0,
    };
    setCommitments((prev) => [c, ...prev]);
  };

  if (loading)
    return (
      <div style={{ padding: 24 }}>
        <SkeletonTable rows={6} cols={4} />
      </div>
    );
  if (error || !engine || !mrp) {
    return (
      <div style={{ padding: 24 }}>
        <Link to="/mrp" style={{ fontSize: 12, color: C.ac, textDecoration: 'none' }}>
          ← MRP
        </Link>
        <EmptyState icon="error" title="Sem dados" description={error || 'Importe ISOP.'} />
      </div>
    );
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1100 }}>
      <Link
        to="/mrp"
        style={{
          fontSize: 12,
          color: C.ac,
          textDecoration: 'none',
          marginBottom: 12,
          display: 'inline-block',
        }}
      >
        ← MRP
      </Link>
      <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: '0 0 4px' }}>
        Capable-to-Promise
      </h1>

      <TrustWarning score={trustScore} />

      <CTPForm
        engine={engine}
        sku={sku}
        setSku={(v) => {
          setSku(v);
          setRan(false);
        }}
        qty={qty}
        setQty={setQty}
        targetDay={targetDay}
        setTargetDay={setTargetDay}
        customer={customer}
        setCustomer={setCustomer}
        onRun={handleRun}
      />

      {ran && scenarios.length > 0 && bestScenario && (
        <>
          <div
            className="mrp__kpis"
            style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginTop: 12 }}
          >
            <KCard
              label="Viável"
              value={bestScenario.result.feasible ? 'SIM' : 'NÃO'}
              sub=""
              color={bestScenario.result.feasible ? C.ac : C.rd}
            />
            <KCard
              label="Dia Mais Cedo"
              value={bestScenario.dateLabel ?? '-'}
              sub={
                bestScenario.result.earliestFeasibleDay != null
                  ? `D${bestScenario.result.earliestFeasibleDay}`
                  : 'sem capacidade'
              }
              color={bestScenario.result.earliestFeasibleDay != null ? C.t1 : C.rd}
            />
            <KCard
              label="Confiança"
              value={
                bestScenario.result.confidence === 'high'
                  ? 'ALTA'
                  : bestScenario.result.confidence === 'medium'
                    ? 'MÉDIA'
                    : 'BAIXA'
              }
              sub=""
              color={
                bestScenario.result.confidence === 'high'
                  ? C.ac
                  : bestScenario.result.confidence === 'medium'
                    ? C.yl
                    : C.rd
              }
            />
            <KCard
              label="Capacidade"
              value={`${bestScenario.result.requiredMin}m`}
              sub={`disponível: ${bestScenario.result.availableMinOnDay}m`}
              color={C.t1}
            />
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
              Cenários ({scenarios.length})
            </div>
            {scenarios.map((s) => (
              <CTPScenarioCard
                key={s.id + s.machine}
                scenario={s}
                engine={engine}
                confidence={confidenceMap.get(s.id + s.machine)}
                onCommit={s.result.feasible ? () => handleCommit(s) : undefined}
              />
            ))}
          </div>

          {bestScenario.result.capacityTimeline.length > 0 && (
            <div className="mrp__card" style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: C.t2, marginBottom: 8 }}>
                Timeline de Capacidade — {bestScenario.machine}
              </div>
              <CTPChart
                timeline={bestScenario.result.capacityTimeline}
                dates={engine.dates}
                dnames={engine.dnames}
                targetDay={targetDay}
              />
            </div>
          )}
        </>
      )}

      {ran && scenarios.length === 0 && (
        <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
          SKU não encontrado ou sem dados CTP
        </div>
      )}

      {commitments.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Compromissos Registados ({commitments.length})
          </div>
          <table className="mrp__table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Cliente</th>
                <th style={{ textAlign: 'right' }}>Qtd</th>
                <th>Data Prometida</th>
                <th>Máquina</th>
                <th>Confiança</th>
              </tr>
            </thead>
            <tbody>
              {commitments.map((c) => (
                <CommitmentRow key={c.id} c={c} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
