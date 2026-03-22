import type React from 'react';
import { C } from '@/theme/color-bridge';
import { Pill } from '../atoms';
import type { OBJECTIVE_PROFILES } from '../constants';
import type { ScenarioConfig } from './whatif-types';

export function OperatorInputs({
  sc,
  setSc,
  setRes,
}: {
  sc: ScenarioConfig;
  setSc: React.Dispatch<React.SetStateAction<ScenarioConfig>>;
  setRes: (r: null) => void;
}) {
  return (
    <>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t3, marginBottom: 5 }}>Operadores</div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr 1fr',
          gap: 6,
          marginBottom: 10,
        }}
      >
        {[
          { l: 'PG1 Eq', k: 't1' as const },
          { l: 'PG1 Pool', k: 'p1' as const },
          { l: 'PG2 Eq', k: 't2' as const },
          { l: 'PG2 Pool', k: 'p2' as const },
        ].map((f) => (
          <div key={f.k}>
            <div style={{ fontSize: 12, color: C.t4, marginBottom: 2 }}>{f.l}</div>
            <input
              type="number"
              value={sc[f.k]}
              onChange={(e) => {
                setSc((p) => ({ ...p, [f.k]: parseInt(e.target.value, 10) || 0 }));
                setRes(null);
              }}
              style={{
                width: '100%',
                padding: 5,
                borderRadius: 6,
                border: `1px solid ${C.bd}`,
                background: C.bg,
                color: C.t1,
                fontSize: 13,
                fontFamily: 'monospace',
                textAlign: 'center',
              }}
            />
          </div>
        ))}
      </div>
    </>
  );
}

export function IterationsPicker({
  N,
  setN,
  setRes,
}: {
  N: number;
  setN: (n: number) => void;
  setRes: (r: null) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: C.t4 }}>Iterações</div>
      {[100, 300, 500, 1000].map((n) => (
        <Pill
          key={n}
          active={N === n}
          color={C.pp}
          onClick={() => {
            setN(n);
            setRes(null);
          }}
          size="sm"
        >
          {n}
        </Pill>
      ))}
    </div>
  );
}

export function SeedInput({
  sc,
  setSc,
  setRes,
}: {
  sc: ScenarioConfig;
  setSc: React.Dispatch<React.SetStateAction<ScenarioConfig>>;
  setRes: (r: null) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: C.t4 }}>Seed</div>
      <input
        type="number"
        value={sc.seed}
        onChange={(e) => {
          setSc((p) => ({ ...p, seed: parseInt(e.target.value, 10) || 0 }));
          setRes(null);
        }}
        style={{
          width: 80,
          padding: 4,
          borderRadius: 6,
          border: `1px solid ${C.bd}`,
          background: C.bg,
          color: C.t1,
          fontSize: 12,
          fontFamily: 'monospace',
          textAlign: 'center',
        }}
      />
      <div style={{ fontSize: 12, color: C.t4 }}>Mesma seed = resultados reprodutiveis</div>
    </div>
  );
}

export function HeuristicPicker({
  dispatchRule,
  setDispatchRule,
  setRes,
}: {
  dispatchRule: string;
  setDispatchRule: (r: 'EDD' | 'CR' | 'WSPT' | 'SPT') => void;
  setRes: (r: null) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: C.t4 }}>Heurística</div>
      {(['EDD', 'CR', 'WSPT', 'SPT'] as const).map((r) => (
        <Pill
          key={r}
          active={dispatchRule === r}
          color={C.bl}
          onClick={() => {
            setDispatchRule(r);
            setRes(null);
          }}
          size="sm"
        >
          {r}
        </Pill>
      ))}
    </div>
  );
}

export function ObjectivePicker({
  objProfile,
  setObjProfile,
  objectiveProfiles,
  setRes,
}: {
  objProfile: string;
  setObjProfile: (id: string) => void;
  objectiveProfiles: typeof OBJECTIVE_PROFILES;
  setRes: (r: null) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: C.t4 }}>Objectivo</div>
      {objectiveProfiles.map((p) => (
        <Pill
          key={p.id}
          active={objProfile === p.id}
          color={C.ac}
          onClick={() => {
            setObjProfile(p.id);
            setRes(null);
          }}
          size="sm"
        >
          {p.label}
        </Pill>
      ))}
    </div>
  );
}

export function QuickScenarios({
  focusIds,
  setResourceDown,
  clearResourceDown,
  setRes,
}: {
  focusIds: string[];
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  setRes: (r: null) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: C.t4, width: '100%', marginBottom: 2 }}>
        Cenarios Rapidos
      </div>
      <Pill
        color={C.rd}
        active={false}
        onClick={() => {
          setResourceDown('machine', 'PRM042', [0, 1]);
          setRes(null);
        }}
        size="sm"
      >
        Avaria PRM042 (2d)
      </Pill>
      <Pill
        color={C.yl}
        active={false}
        onClick={() => {
          setResourceDown('machine', 'PRM039', [0]);
          setRes(null);
        }}
        size="sm"
      >
        Avaria PRM039 (1d)
      </Pill>
      <Pill
        color={C.bl}
        active={false}
        onClick={() => {
          for (const m of focusIds) clearResourceDown('machine', m);
          setRes(null);
        }}
        size="sm"
      >
        Limpar Cenario
      </Pill>
    </div>
  );
}
