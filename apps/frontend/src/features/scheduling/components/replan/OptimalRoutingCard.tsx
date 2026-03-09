/**
 * OptimalRoutingCard — Optimization results, GA/SA controls, routing display.
 */

import { Sparkles, Zap } from 'lucide-react';
import React from 'react';
import { C } from '../../../../lib/engine';
import { Card, Pill, toolColor } from '../atoms';
import { OptResultsList } from './OptResultsList';
import type { OptimalRoutingCardProps } from './types';

export function OptimalRoutingCard({
  tools,
  optRunning,
  optResults,
  optProgress,
  optN,
  optProfile,
  optMoveable,
  saRunning,
  saProgress,
  setOptN,
  setOptProfile,
  setOptResults,
  runOpt,
  runSA,
  cancelSA,
  applyOptResult,
  profiles,
}: OptimalRoutingCardProps) {
  return (
    <Card style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 10,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
          <Sparkles
            size={12}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4, color: C.pp }}
          />
          Optimização{' '}
          <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>
            {optMoveable.length} ops movíveis
          </span>
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          marginBottom: 10,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div
            style={{
              fontSize: 9,
              color: C.t4,
              marginBottom: 2,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '.04em',
            }}
          >
            Perfil
          </div>
          <div style={{ display: 'flex', gap: 3 }}>
            {profiles.map((p) => (
              <Pill
                key={p.id}
                active={optProfile === p.id}
                color={C.pp}
                onClick={() => {
                  setOptProfile(p.id);
                  setOptResults([]);
                }}
                size="sm"
              >
                {p.label}
              </Pill>
            ))}
          </div>
        </div>
        <div>
          <div
            style={{
              fontSize: 9,
              color: C.t4,
              marginBottom: 2,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '.04em',
            }}
          >
            Iterações
          </div>
          <div style={{ display: 'flex', gap: 3 }}>
            {[100, 200, 500].map((n) => (
              <Pill
                key={n}
                active={optN === n}
                color={C.bl}
                onClick={() => {
                  setOptN(n);
                  setOptResults([]);
                }}
                size="sm"
              >
                {n}
              </Pill>
            ))}
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={runOpt}
          disabled={optRunning}
          data-testid="run-optimization"
          style={{
            padding: '8px 20px',
            borderRadius: 6,
            border: 'none',
            background: optRunning ? C.s3 : C.pp,
            color: optRunning ? C.t3 : C.t1,
            fontSize: 11,
            fontWeight: 600,
            cursor: optRunning ? 'wait' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          <Sparkles
            size={11}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}
          />
          {optRunning ? `A optimizar... ${Math.round(optProgress * 100)}%` : 'Otimizar'}
        </button>
        <button
          onClick={saRunning ? cancelSA : runSA}
          disabled={optRunning}
          data-testid="run-sa"
          style={{
            padding: '8px 20px',
            borderRadius: 6,
            border: 'none',
            background: saRunning ? C.s3 : '#1a6b3a',
            color: saRunning ? C.t3 : C.t1,
            fontSize: 11,
            fontWeight: 600,
            cursor: optRunning ? 'not-allowed' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          <Zap
            size={11}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}
          />
          {saRunning
            ? `SA ${saProgress != null ? `${saProgress}%` : '...'} (cancelar)`
            : 'SA Otimizar'}
        </button>
      </div>

      {/* SA Progress Bar */}
      {saRunning && saProgress != null && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ height: 4, borderRadius: 2, background: C.s3, overflow: 'hidden' }}>
            <div
              style={{
                height: '100%',
                width: `${saProgress}%`,
                background: '#1a6b3a',
                borderRadius: 2,
                transition: 'width 0.3s ease',
              }}
            />
          </div>
          <div style={{ fontSize: 10, color: C.t3, marginTop: 2 }}>
            Simulated Annealing em execucao (Web Worker) — {saProgress}%
          </div>
        </div>
      )}

      {/* Moveable ops summary */}
      {optMoveable.length > 0 && !optResults.length && (
        <div style={{ maxHeight: 120, overflowY: 'auto', marginBottom: 6 }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '70px 60px 50px 50px 1fr',
              gap: '2px 8px',
              fontSize: 10,
            }}
          >
            <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Ferramenta</div>
            <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Prim.</div>
            <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Alt.</div>
            <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Pcs</div>
            <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Horas</div>
            {optMoveable.slice(0, 12).map((mo) => (
              <React.Fragment key={mo.opId}>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono',monospace",
                    color: toolColor(tools, mo.toolId),
                    fontWeight: 600,
                  }}
                >
                  {mo.toolId}
                </div>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t2 }}>
                  {mo.primaryM}
                </div>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.ac }}>
                  {mo.altM}
                </div>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t1 }}>
                  {mo.totalPcs.toLocaleString()}
                </div>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t3 }}>
                  {mo.hrs.toFixed(1)}h
                </div>
              </React.Fragment>
            ))}
          </div>
          {optMoveable.length > 12 && (
            <div style={{ fontSize: 9, color: C.t4, textAlign: 'center', marginTop: 4 }}>
              +{optMoveable.length - 12} mais
            </div>
          )}
        </div>
      )}

      {/* Optimization results */}
      <OptResultsList optResults={optResults} applyOptResult={applyOptResult} />

      {optMoveable.length === 0 && (
        <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
          Sem operações movíveis (todas as ferramentas numa só máquina)
        </div>
      )}
    </Card>
  );
}
