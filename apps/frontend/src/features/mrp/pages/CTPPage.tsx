/**
 * CTPPage — Capable-to-Promise standalone page with 3-scenario simulation.
 * Route: /mrp/ctp
 * Uses backend POST /v1/schedule/ctp — no client-side CTP computation.
 */

import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { getCachedNikufraData, useScheduleData } from '@/hooks/useScheduleData';
import type { CTPApiScenario } from '@/lib/api';
import { scheduleCTPApi } from '@/lib/api';
import { useDataStore } from '@/stores/useDataStore';
import { C } from '@/theme/color-bridge';
import { CTPChart } from '../components/CTPChart';
import { CTPCommitmentsTable } from '../components/CTPCommitmentsTable';
import { CTPForm } from '../components/CTPForm';
import { CTPScenarioCard } from '../components/CTPScenarioCard';
import { CTPTrustWarning } from '../components/CTPTrustWarning';
import { KCard } from '../components/KCard';
import type { CTPCommitment } from '../utils/ctp-compute';
import { computeConfidenceInterval } from '../utils/ctp-compute';

/** Map backend CTPApiScenario to the shape CTPScenarioCard expects. */
function toScenarioCardProps(s: CTPApiScenario) {
  return {
    id: s.id as 'best' | 'tradeoff' | 'infeasible',
    label: s.label,
    machine: s.machine,
    isAlt: s.is_alt,
    dateLabel: s.date_label,
    result: {
      feasible: s.feasible,
      earliestFeasibleDay: s.earliest_feasible_day,
      requiredMin: s.required_min,
      availableMinOnDay: s.available_min_on_day,
      capacitySlack: s.capacity_slack,
      confidence: s.confidence,
      reason: s.reason,
      machine: s.machine,
      toolCode: '',
      projectedStockOnDay: 0,
      stockAfterOrder: 0,
      capacityTimeline: s.capacity_timeline.map((c) => ({
        dayIndex: c.day_index,
        existingLoad: c.existing_load,
        newOrderLoad: c.new_order_load,
        capacity: c.capacity,
      })),
    },
  };
}

export function CTPPage() {
  const { engine, loading, error } = useScheduleData();
  const trustScore = useDataStore((s) => s.meta?.trustScore) ?? 0.5;

  const [sku, setSku] = useState('');
  const [qty, setQty] = useState(5000);
  const [targetDay, setTargetDay] = useState(0);
  const [customer, setCustomer] = useState('');
  const [commitments, setCommitments] = useState<CTPCommitment[]>([]);
  const [scenarios, setScenarios] = useState<CTPApiScenario[]>([]);
  const [ctpLoading, setCtpLoading] = useState(false);
  const [ran, setRan] = useState(false);

  const handleRun = useCallback(async () => {
    if (!sku || qty <= 0) return;
    const nikufraData = getCachedNikufraData();
    if (!nikufraData) return;

    setRan(true);
    setCtpLoading(true);
    try {
      const response = await scheduleCTPApi({
        nikufra_data: nikufraData,
        sku,
        quantity: qty,
        target_day: targetDay,
      });
      setScenarios(response.scenarios);
    } catch {
      setScenarios([]);
    } finally {
      setCtpLoading(false);
    }
  }, [sku, qty, targetDay]);

  const scenarioProps = useMemo(() => scenarios.map(toScenarioCardProps), [scenarios]);
  const bestScenario = scenarioProps.find((s) => s.result.feasible) ?? scenarioProps[0] ?? null;

  const confidenceMap = useMemo(() => {
    if (!engine) return new Map<string, ReturnType<typeof computeConfidenceInterval>>();
    const map = new Map<string, ReturnType<typeof computeConfidenceInterval>>();
    for (const s of scenarioProps) {
      map.set(s.id + s.machine, computeConfidenceInterval(s.result, trustScore, engine));
    }
    return map;
  }, [scenarioProps, trustScore, engine]);

  const handleCommit = (s: (typeof scenarioProps)[0]) => {
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
  if (error || !engine) {
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

      <CTPTrustWarning score={trustScore} />

      <CTPForm
        engine={engine}
        sku={sku}
        setSku={(v) => {
          setSku(v);
          setRan(false);
          setScenarios([]);
        }}
        qty={qty}
        setQty={setQty}
        targetDay={targetDay}
        setTargetDay={setTargetDay}
        customer={customer}
        setCustomer={setCustomer}
        onRun={handleRun}
      />

      {ctpLoading && (
        <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
          A calcular CTP...
        </div>
      )}

      {ran && !ctpLoading && scenarioProps.length > 0 && bestScenario && (
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
              Cenários ({scenarioProps.length})
            </div>
            {scenarioProps.map((s) => (
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

      {ran && !ctpLoading && scenarioProps.length === 0 && (
        <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
          SKU não encontrado ou sem dados CTP
        </div>
      )}

      <CTPCommitmentsTable commitments={commitments} />
    </div>
  );
}
