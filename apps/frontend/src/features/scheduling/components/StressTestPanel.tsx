/**
 * StressTestPanel — 6 predefined stress tests + fragility score.
 *
 * Each test clones the current plan, applies a perturbation,
 * re-schedules, and compares KPIs with the baseline.
 */

import { useState } from 'react';
import type { Block, EngineData, EOp, OptResult } from '../../../lib/engine';
import { C } from '../../../lib/engine';
import type { StressTestResult } from '../hooks/useStressTest';
import { useStressTest } from '../hooks/useStressTest';
import { Card } from './atoms';
import './StressTestPanel.css';

interface StressTestPanelProps {
  data: EngineData;
  blocks: Block[];
  allOps: EOp[];
  baselineMetrics: OptResult | null;
}

function scoreColor(score: number): string {
  if (score >= 7) return 'stress-panel__test-score--good';
  if (score >= 4) return 'stress-panel__test-score--moderate';
  return 'stress-panel__test-score--bad';
}

function fragilityLabel(score: number): { label: string; color: string } {
  if (score >= 7) return { label: 'ROBUSTO', color: C.ac };
  if (score >= 4) return { label: 'MODERADO', color: C.yl };
  return { label: 'FRAGIL', color: C.rd };
}

function deltaClass(baseline: number, stressed: number, lowerIsBetter: boolean): string {
  const diff = stressed - baseline;
  if (Math.abs(diff) < 0.1) return 'stress-panel__detail-val';
  const worse = lowerIsBetter ? diff > 0 : diff < 0;
  return worse
    ? 'stress-panel__detail-val stress-panel__detail-val--worse'
    : 'stress-panel__detail-val stress-panel__detail-val--better';
}

function TestDetail({ result }: { result: StressTestResult }) {
  return (
    <div className="stress-panel__detail">
      <div className="stress-panel__detail-label">Metrica</div>
      <div className="stress-panel__detail-label">Baseline</div>
      <div className="stress-panel__detail-label">Stressed</div>
      <div className="stress-panel__detail-label">Delta</div>

      <div className="stress-panel__detail-val">OTD-D</div>
      <div className="stress-panel__detail-val">{result.baseline.otd.toFixed(1)}%</div>
      <div className={deltaClass(result.baseline.otd, result.stressed.otd, false)}>
        {result.stressed.otd.toFixed(1)}%
      </div>
      <div className={deltaClass(result.baseline.otd, result.stressed.otd, false)}>
        {(result.stressed.otd - result.baseline.otd).toFixed(1)}%
      </div>

      <div className="stress-panel__detail-val">Setups</div>
      <div className="stress-panel__detail-val">{(result.baseline.setupMin / 60).toFixed(1)}h</div>
      <div className={deltaClass(result.baseline.setupMin, result.stressed.setupMin, true)}>
        {(result.stressed.setupMin / 60).toFixed(1)}h
      </div>
      <div className={deltaClass(result.baseline.setupMin, result.stressed.setupMin, true)}>
        {((result.stressed.setupMin - result.baseline.setupMin) / 60).toFixed(1)}h
      </div>

      <div className="stress-panel__detail-val">Tardiness</div>
      <div className="stress-panel__detail-val">{result.baseline.tardiness}d</div>
      <div className={deltaClass(result.baseline.tardiness, result.stressed.tardiness, true)}>
        {result.stressed.tardiness}d
      </div>
      <div className={deltaClass(result.baseline.tardiness, result.stressed.tardiness, true)}>
        {result.stressed.tardiness - result.baseline.tardiness > 0 ? '+' : ''}
        {result.stressed.tardiness - result.baseline.tardiness}d
      </div>

      <div className="stress-panel__detail-val">Overflows</div>
      <div className="stress-panel__detail-val">{result.baseline.overflows}</div>
      <div className={deltaClass(result.baseline.overflows, result.stressed.overflows, true)}>
        {result.stressed.overflows}
      </div>
      <div className={deltaClass(result.baseline.overflows, result.stressed.overflows, true)}>
        {result.stressed.overflows - result.baseline.overflows > 0 ? '+' : ''}
        {result.stressed.overflows - result.baseline.overflows}
      </div>
    </div>
  );
}

export function StressTestPanel({ data, blocks, allOps, baselineMetrics }: StressTestPanelProps) {
  const { results, fragilityScore, running, runAll, runSingle } = useStressTest(
    data,
    blocks,
    allOps,
    baselineMetrics,
  );
  const [expanded, setExpanded] = useState<string | null>(null);

  const passedCount = results.filter((r) => r.passed).length;
  const weakest = results.length > 0 ? results.reduce((a, b) => (a.score < b.score ? a : b)) : null;
  const frag = fragilityLabel(fragilityScore);

  return (
    <Card style={{ padding: 14 }}>
      <div className="stress-panel">
        <div className="stress-panel__header">
          <div className="stress-panel__title">Stress Tests — Robustez do Plano</div>
          <button
            className="stress-panel__btn stress-panel__btn--primary"
            onClick={runAll}
            disabled={running || !baselineMetrics}
          >
            {running ? 'A executar...' : 'Executar Todos'}
          </button>
        </div>

        {[
          { id: 'ST-001', name: 'Avaria PRM039 (8h)', desc: 'Máquina PRM039 indisponível 1 dia' },
          { id: 'ST-002', name: 'Fornecedor atrasa 3d', desc: 'Todas as deadlines +3 dias' },
          { id: 'ST-003', name: 'Procura +20%', desc: 'Toda a procura aumenta 20%' },
          { id: 'ST-004', name: '2 operadores faltam', desc: 'PG1 perde 2 operadores' },
          { id: 'ST-005', name: 'Rejeicao sobe 5%', desc: 'Produzir 5% mais pecas' },
          { id: 'ST-006', name: 'Falha energia 2h', desc: '120min perdidos em todas máquinas' },
        ].map((test) => {
          const result = results.find((r) => r.id === test.id);
          const isExpanded = expanded === test.id;
          return (
            <div key={test.id}>
              <div
                className="stress-panel__test"
                onClick={() => result && setExpanded(isExpanded ? null : test.id)}
              >
                <span className="stress-panel__test-id">{test.id}</span>
                <div className="stress-panel__test-info">
                  <div className="stress-panel__test-name">{test.name}</div>
                  <div className="stress-panel__test-desc">{test.desc}</div>
                </div>
                {result ? (
                  <span className={`stress-panel__test-score ${scoreColor(result.score)}`}>
                    {result.score}/10
                  </span>
                ) : (
                  <span className="stress-panel__test-score" style={{ color: C.t4 }}>
                    —
                  </span>
                )}
                <button
                  className="stress-panel__test-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    runSingle(test.id);
                  }}
                  disabled={running}
                >
                  Executar
                </button>
              </div>
              {isExpanded && result && <TestDetail result={result} />}
            </div>
          );
        })}

        {results.length > 0 && (
          <div className="stress-panel__fragility">
            <div className="stress-panel__fragility-score" style={{ color: frag.color }}>
              {fragilityScore}/10
            </div>
            <div className="stress-panel__fragility-label" style={{ color: frag.color }}>
              {frag.label}
            </div>
            <div className="stress-panel__fragility-detail">
              Plano sobrevive {passedCount}/6 cenarios com OTD-D {'>'} 85%
              {weakest && (
                <>
                  {' '}
                  · Ponto fraco: {weakest.name} (OTD-D {weakest.stressed.otd.toFixed(1)}%)
                </>
              )}
            </div>
            <div className="stress-panel__fragility-bar">
              <div
                className="stress-panel__fragility-bar-fill"
                style={{
                  width: `${(fragilityScore / 10) * 100}%`,
                  background: frag.color,
                }}
              />
            </div>
          </div>
        )}

        {results.length > 0 && fragilityScore < 4 && (
          <div className="stress-panel__alert">
            Plano fragil. Considere alternativas ou reforce capacidade.
          </div>
        )}
      </div>
    </Card>
  );
}
