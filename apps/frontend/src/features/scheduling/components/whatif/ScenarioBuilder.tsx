import type React from 'react';
import type { EngineData, ETool } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Card, dot, Pill, Tag } from '../atoms';
import type { OBJECTIVE_PROFILES } from '../constants';
import { DownPeriodEditor } from './DownPeriodEditor';
import {
  HeuristicPicker,
  IterationsPicker,
  ObjectivePicker,
  OperatorInputs,
  QuickScenarios,
  SeedInput,
} from './ScenarioConfigInputs';
import type { EditingDown, ScenarioConfig } from './whatif-types';

export function ScenarioBuilder({
  data,
  sc,
  setSc,
  N,
  setN,
  dispatchRule,
  setDispatchRule,
  objProfile,
  setObjProfile,
  objectiveProfiles,
  editingDown,
  setEditingDown,
  wdi,
  wiDownStartDay,
  setWiDownStartDay,
  wiDownEndDay,
  setWiDownEndDay,
  getResourceDownDays,
  setResourceDown,
  clearResourceDown,
  setRes,
  focusT,
  run,
  prog,
  optimize,
}: {
  data: EngineData;
  sc: ScenarioConfig;
  setSc: React.Dispatch<React.SetStateAction<ScenarioConfig>>;
  N: number;
  setN: (n: number) => void;
  dispatchRule: string;
  setDispatchRule: (r: 'EDD' | 'CR' | 'WSPT' | 'SPT') => void;
  objProfile: string;
  setObjProfile: (id: string) => void;
  objectiveProfiles: typeof OBJECTIVE_PROFILES;
  editingDown: EditingDown;
  setEditingDown: (ed: EditingDown) => void;
  wdi: number[];
  wiDownStartDay: number;
  setWiDownStartDay: (d: number) => void;
  wiDownEndDay: number;
  setWiDownEndDay: (d: number) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  setRes: (r: null) => void;
  focusT: ETool[];
  run: boolean;
  prog: number;
  optimize: () => void;
}) {
  const { machines, dates, dnames, focusIds } = data;

  return (
    <Card style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>Simulação de Cenários</div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(() => {
            const n = machines.filter((m) => getResourceDownDays('machine', m.id).size > 0).length;
            return n > 0 ? <Tag color={C.rd}>{n} máquinas paradas</Tag> : null;
          })()}
          {(() => {
            const n = focusT.filter((t) => getResourceDownDays('tool', t.id).size > 0).length;
            return n > 0 ? <Tag color={C.yl}>{n} ferramentas paradas</Tag> : null;
          })()}
          <Tag color={C.pp}>N={N}</Tag>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <ResourcePickers
            focusIds={focusIds}
            focusT={focusT}
            editingDown={editingDown}
            setEditingDown={setEditingDown}
            getResourceDownDays={getResourceDownDays}
            setRes={setRes}
          />
          {editingDown && (
            <DownPeriodEditor
              editingDown={editingDown}
              setEditingDown={setEditingDown}
              dates={dates}
              dnames={dnames}
              wdi={wdi}
              wiDownStartDay={wiDownStartDay}
              setWiDownStartDay={setWiDownStartDay}
              wiDownEndDay={wiDownEndDay}
              setWiDownEndDay={setWiDownEndDay}
              getResourceDownDays={getResourceDownDays}
              setResourceDown={setResourceDown}
              clearResourceDown={clearResourceDown}
              setRes={setRes}
            />
          )}
        </div>
        <div>
          <OperatorInputs sc={sc} setSc={setSc} setRes={setRes} />
          <IterationsPicker N={N} setN={setN} setRes={setRes} />
          <SeedInput sc={sc} setSc={setSc} setRes={setRes} />
          <HeuristicPicker
            dispatchRule={dispatchRule}
            setDispatchRule={setDispatchRule}
            setRes={setRes}
          />
          <ObjectivePicker
            objProfile={objProfile}
            setObjProfile={setObjProfile}
            objectiveProfiles={objectiveProfiles}
            setRes={setRes}
          />
          <QuickScenarios
            focusIds={focusIds}
            setResourceDown={setResourceDown}
            clearResourceDown={clearResourceDown}
            setRes={setRes}
          />
          <button
            onClick={optimize}
            disabled={run}
            style={{
              width: '100%',
              padding: 12,
              borderRadius: 8,
              border: 'none',
              cursor: run ? 'wait' : 'pointer',
              background: run ? C.s3 : C.ac,
              color: run ? C.t3 : C.bg,
              fontSize: 13,
              fontWeight: 600,
              fontFamily: 'inherit',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {run && (
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${prog}%`,
                  background: `${C.w}15`,
                  transition: 'width .1s',
                }}
              />
            )}
            <span style={{ position: 'relative' }}>
              {run ? `A simular... ${prog}%` : 'SIMULAR — encontrar melhores planos'}
            </span>
          </button>
        </div>
      </div>
    </Card>
  );
}

function ResourcePickers({
  focusIds,
  focusT,
  editingDown,
  setEditingDown,
  getResourceDownDays,
  setRes,
}: {
  focusIds: string[];
  focusT: ETool[];
  editingDown: EditingDown;
  setEditingDown: (ed: EditingDown) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  setRes: (r: null) => void;
}) {
  return (
    <>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t3, marginBottom: 6 }}>Máquinas</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
        {focusIds.map((id) => {
          const downDays = getResourceDownDays('machine', id);
          return (
            <Pill
              key={id}
              active={downDays.size > 0}
              color={C.rd}
              onClick={() => {
                setEditingDown(
                  editingDown?.type === 'machine' && editingDown.id === id
                    ? null
                    : { type: 'machine', id },
                );
                setRes(null);
              }}
              size="sm"
            >
              <span style={dot(downDays.size > 0 ? C.rd : C.ac, downDays.size > 0)} />
              {id}
              {downDays.size > 0 ? ` ${downDays.size}d` : ''}
            </Pill>
          );
        })}
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t3, marginBottom: 6 }}>Ferramentas</div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 3,
          maxHeight: 60,
          overflowY: 'auto',
        }}
      >
        {focusT.map((t) => {
          const tDown = getResourceDownDays('tool', t.id);
          return (
            <Pill
              key={t.id}
              active={tDown.size > 0}
              color={C.rd}
              onClick={() => {
                setEditingDown(
                  editingDown?.type === 'tool' && editingDown.id === t.id
                    ? null
                    : { type: 'tool', id: t.id },
                );
                setRes(null);
              }}
              size="sm"
            >
              {t.id}
              {tDown.size > 0 ? ` ${tDown.size}d` : ''}
            </Pill>
          );
        })}
      </div>
    </>
  );
}
