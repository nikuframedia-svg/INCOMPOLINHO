/**
 * GanttSplitPane — Split layout: OperationsTable (left) + GanttChart (right) + CapacityHistogram.
 * Wraps the existing GanttView and adds drag-and-drop with DeviationPanel overlay.
 */

import { useCallback, useRef, useState } from 'react';
import type {
  Block,
  DayLoad,
  EngineData,
  EOp,
  OptResult,
  ScheduleValidationReport,
} from '../../../../lib/engine';
// scoreSchedule removed — metrics come from backend via neMetrics prop
import { useClassifications } from '../../../../hooks/useClassifications';
import { useGanttDragDrop } from '../../hooks/useGanttDragDrop';
import { CapacityHistogram } from './CapacityHistogram';
import { DeviationPanel } from './DeviationPanel';
import { GanttView } from './GanttChart';
import { OperationsTable } from './OperationsTable';
import './GanttSplitPane.css';

interface GanttSplitPaneProps {
  blocks: Block[];
  mSt: Record<string, string>;
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  validation?: ScheduleValidationReport | null;
  allOps?: EOp[];
  neMetrics?: OptResult | null;
}

export function GanttSplitPane({
  blocks,
  mSt,
  cap,
  data,
  applyMove,
  undoMove,
  validation,
  allOps: _allOps,
  neMetrics,
}: GanttSplitPaneProps) {
  const [selectedOpId, setSelectedOpId] = useState<string | null>(null);
  const [dayIdx, setDayIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Current metrics from backend (no local scoreSchedule)
  const currentMetrics = neMetrics ?? null;

  const { blockDefinitions } = useClassifications();
  const { proposedMove, clearProposal, pushUndo } = useGanttDragDrop(data.machines, 44, 1);

  const handleSelectBlock = useCallback((block: Block) => {
    setSelectedOpId(block.opId);
    setDayIdx(block.dayIdx);
  }, []);

  const handleConfirmMove = useCallback(() => {
    if (!proposedMove) return;
    applyMove(proposedMove.block.opId, proposedMove.toMachineId);
    pushUndo(`${proposedMove.block.toolId} → ${proposedMove.toMachineId}`);
    clearProposal();
  }, [proposedMove, applyMove, pushUndo, clearProposal]);

  return (
    <div className="gantt-split" ref={containerRef}>
      <div className="gantt-split__body">
        <div className="gantt-split__left">
          <OperationsTable
            blocks={blocks}
            selectedOpId={selectedOpId}
            onSelectBlock={handleSelectBlock}
            dayIdx={dayIdx}
            dates={data.dates}
          />
        </div>
        <div className="gantt-split__right">
          <div className="gantt-split__gantt">
            <GanttView
              blocks={blocks}
              mSt={mSt}
              cap={cap}
              data={data}
              applyMove={applyMove}
              undoMove={undoMove}
              validation={validation}
              currentMetrics={currentMetrics}
              blockClassifications={blockDefinitions}
            />
          </div>
          <div className="gantt-split__histogram">
            <CapacityHistogram cap={cap} machines={data.machines} dayIdx={dayIdx} />
          </div>
        </div>
      </div>

      {proposedMove && (
        <DeviationPanel
          move={proposedMove}
          blocks={blocks}
          currentMetrics={currentMetrics}
          onConfirm={handleConfirmMove}
          onCancel={clearProposal}
        />
      )}
    </div>
  );
}
