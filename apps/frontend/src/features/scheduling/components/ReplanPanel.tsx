/**
 * ReplanPanel — Orchestrator for all replan sub-components.
 * Delegates rendering to focused sub-components in ./replan/.
 */
import { AlertTriangle } from 'lucide-react';
import type React from 'react';
import type { Block, DayLoad, EngineData, EOp, MoveAction, OptResult } from '../../../lib/engine';
import { type buildResourceTimelines, C } from '../../../lib/engine';
import { useReplanOrchestrator } from '../hooks/useReplanOrchestrator';
import { OBJECTIVE_PROFILES } from './constants';
import { ReplanKPIPreview } from './ReplanKPIPreview';
import { ReplanStrategyCard } from './ReplanStrategyCard';
import { ReplanTimeline } from './ReplanTimeline';
import {
  AutoReplanCard,
  DayRangePicker,
  DecisionsPanel,
  FailureFormCard,
  OptimalRoutingCard,
  ResourceDownCard,
  RushOrderCard,
} from './replan';

function QualityBanner({
  qv,
}: {
  qv: { criticalCount: number; highCount: number; warnings: string[] };
}) {
  if (qv.criticalCount === 0 && qv.highCount === 0) return null;
  const isCrit = qv.criticalCount > 0;
  const color = isCrit ? C.rd : C.yl;
  const bg = isCrit ? C.rdS : `${C.yl}18`;
  const critTxt = isCrit
    ? `${qv.criticalCount} conflito${qv.criticalCount > 1 ? 's' : ''} crítico${qv.criticalCount > 1 ? 's' : ''}`
    : '';
  const highTxt = qv.highCount > 0 ? `${qv.highCount} alerta${qv.highCount > 1 ? 's' : ''}` : '';
  const sep = critTxt && highTxt ? ' · ' : '';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 6,
        background: bg,
        borderLeft: `3px solid ${color}`,
      }}
    >
      <AlertTriangle size={13} style={{ color, flexShrink: 0 }} />
      <span style={{ fontSize: 10, fontWeight: 600, color }}>
        {critTxt}
        {sep}
        {highTxt}
      </span>
      {qv.warnings.length > 0 && (
        <span style={{ fontSize: 9, color: C.t3, marginLeft: 'auto' }}>{qv.warnings[0]}</span>
      )}
    </div>
  );
}

export function ReplanView({
  mSt,
  tSt,
  moves,
  applyMove,
  undoMove,
  blocks,
  cap,
  data,
  onApplyAndSave,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
  rushOrders,
  setRushOrders,
  allOps,
  neMetrics,
}: {
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  toggleM?: (id: string) => void;
  toggleT?: (id: string) => void;
  moves: MoveAction[];
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  onApplyAndSave?: () => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >;
  allOps: EOp[];
  neMetrics: (OptResult & { blocks: Block[] }) | null;
}) {
  const { machines, tools, dates, dnames, toolMap: TM, focusIds } = data;
  const {
    rpc,
    rpcActions,
    replanEntries,
    undoEntry,
    clearHistory,
    replanPreview,
    setReplanPreview,
  } = useReplanOrchestrator(
    data,
    blocks,
    allOps,
    mSt,
    tSt,
    moves,
    applyMove,
    replanTimelines,
    OBJECTIVE_PROFILES,
    setRushOrders,
    neMetrics,
  );

  const { xai, editingDown, decs, qv } = rpc;
  const { setXai, setEditingDown } = rpcActions;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <QualityBanner qv={qv} />

      <ResourceDownCard
        machines={machines}
        tools={tools}
        focusIds={focusIds}
        mSt={mSt}
        tSt={tSt}
        editingDown={editingDown}
        setEditingDown={setEditingDown}
        blockCountByMachine={rpc.blockCountByMachine}
        getResourceDownDays={getResourceDownDays}
        setResourceDown={setResourceDown}
        clearResourceDown={clearResourceDown}
        moves={moves}
        undoMove={undoMove}
        applyMove={applyMove}
        onApplyAndSave={onApplyAndSave}
        isSaving={isSaving}
        decs={decs}
        dates={dates}
        dnames={dnames}
        wdi={rpc.wdi}
        downStartDay={rpc.downStartDay}
        downEndDay={rpc.downEndDay}
        setDownStartDay={rpcActions.setDownStartDay}
        setDownEndDay={rpcActions.setDownEndDay}
      />

      {editingDown && (
        <DayRangePicker
          editingDown={editingDown}
          currentDown={getResourceDownDays(editingDown.type, editingDown.id)}
          dates={dates}
          dnames={dnames}
          wdi={rpc.wdi}
          downStartDay={rpc.downStartDay}
          downEndDay={rpc.downEndDay}
          setDownStartDay={rpcActions.setDownStartDay}
          setDownEndDay={rpcActions.setDownEndDay}
          setEditingDown={setEditingDown}
          setResourceDown={setResourceDown}
          clearResourceDown={clearResourceDown}
        />
      )}

      <AutoReplanCard
        wdi={rpc.wdi}
        dates={dates}
        dnames={dnames}
        nDays={data.nDays}
        tools={tools}
        focusIds={focusIds}
        arRunning={rpc.arRunning}
        arResult={rpc.arResult}
        arActions={rpc.arActions}
        arSim={rpc.arSim}
        arSimId={rpc.arSimId}
        arExclude={rpc.arExclude}
        arDayFrom={rpc.arDayFrom}
        arDayTo={rpc.arDayTo}
        arExpanded={rpc.arExpanded}
        arShowExclude={rpc.arShowExclude}
        setArExclude={rpcActions.setArExclude}
        setArDayFrom={rpcActions.setArDayFrom}
        setArDayTo={rpcActions.setArDayTo}
        setArExpanded={rpcActions.setArExpanded}
        setArShowExclude={rpcActions.setArShowExclude}
        setArResult={rpcActions.setArResult}
        runAutoReplan={rpcActions.runAutoReplan}
        handleArUndo={rpcActions.handleArUndo}
        handleArAlt={rpcActions.handleArAlt}
        handleArSimulate={rpcActions.handleArSimulate}
        handleArUndoAll={rpcActions.handleArUndoAll}
        handleArApplyAll={rpcActions.handleArApplyAll}
      />

      <FailureFormCard
        machines={machines}
        tools={tools}
        focusIds={focusIds}
        failures={rpc.failures}
        failureImpacts={rpc.failureImpacts}
        showFailureForm={rpc.showFailureForm}
        ffResType={rpc.ffResType}
        ffResId={rpc.ffResId}
        ffSev={rpc.ffSev}
        ffCap={rpc.ffCap}
        ffStartDay={rpc.ffStartDay}
        ffEndDay={rpc.ffEndDay}
        ffDesc={rpc.ffDesc}
        cascRunning={rpc.cascRunning}
        wdi={rpc.wdi}
        dates={dates}
        dnames={dnames}
        setShowFailureForm={rpcActions.setShowFailureForm}
        setFfResType={rpcActions.setFfResType}
        setFfResId={rpcActions.setFfResId}
        setFfSev={rpcActions.setFfSev}
        setFfCap={rpcActions.setFfCap}
        setFfStartDay={rpcActions.setFfStartDay}
        setFfEndDay={rpcActions.setFfEndDay}
        setFfDesc={rpcActions.setFfDesc}
        addFailure={rpcActions.addFailure}
        removeFailure={rpcActions.removeFailure}
        runCascadingReplan={rpcActions.runCascadingReplan}
      />

      {rpc.failures.length > 0 && rpc.failureImpacts.length > 0 && (
        <ReplanStrategyCard
          failures={rpc.failures}
          impacts={rpc.failureImpacts}
          blocks={blocks}
          onSelectStrategy={rpcActions.setSelectedStrategy}
          selectedStrategy={rpc.selectedStrategy}
        />
      )}

      {replanPreview && (
        <ReplanKPIPreview
          before={replanPreview.before}
          after={replanPreview.after}
          movesCount={replanPreview.movesCount}
          onApply={() => {
            replanPreview.pendingApply?.();
            setReplanPreview(null);
          }}
          onCancel={() => setReplanPreview(null)}
        />
      )}

      <OptimalRoutingCard
        tools={tools}
        optRunning={rpc.optRunning}
        optResults={rpc.optResults}
        optProgress={rpc.optProgress}
        optN={rpc.optN}
        optProfile={rpc.optProfile}
        optMoveable={rpc.optMoveable}
        saRunning={rpc.saRunning}
        saProgress={rpc.saProgress}
        setOptN={rpcActions.setOptN}
        setOptProfile={rpcActions.setOptProfile}
        setOptResults={rpcActions.setOptResults}
        runOpt={rpcActions.runOpt}
        runSA={rpcActions.runSA}
        cancelSA={rpcActions.cancelSA}
        applyOptResult={rpcActions.applyOptResult}
        profiles={OBJECTIVE_PROFILES}
      />

      <RushOrderCard
        tools={tools}
        focusIds={focusIds}
        toolMap={TM}
        rushOrders={rushOrders}
        roTool={rpc.roTool}
        roQty={rpc.roQty}
        roDeadline={rpc.roDeadline}
        wdi={rpc.wdi}
        dates={dates}
        dnames={dnames}
        setRoTool={rpcActions.setRoTool}
        setRoQty={rpcActions.setRoQty}
        setRoDeadline={rpcActions.setRoDeadline}
        addRushOrder={rpcActions.addRushOrder}
        removeRushOrder={rpcActions.removeRushOrder}
      />

      <DecisionsPanel
        data={data}
        blocks={blocks}
        cap={cap}
        mSt={mSt}
        moves={moves}
        undoMove={undoMove}
        applyMove={applyMove}
        decs={decs}
        xai={xai}
        setXai={setXai}
        neMetrics={neMetrics}
      />

      <ReplanTimeline
        entries={replanEntries}
        onUndo={(id) => {
          const entry = undoEntry(id);
          if (entry) {
            for (const mv of entry.moves) undoMove(mv.opId);
          }
        }}
        onClear={clearHistory}
      />
    </div>
  );
}
