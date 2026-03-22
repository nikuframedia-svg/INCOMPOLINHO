/** useGanttDragDrop — Drag-and-drop for Gantt blocks with 5px threshold + DeviationPanel integration. */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Block, EMachine } from '@/domain/types/scheduling';
import { S0, S1 } from '@/domain/types/scheduling';

export interface DragState {
  isDragging: boolean;
  block: Block | null;
  offsetX: number;
  offsetY: number;
  ghostX: number;
  ghostY: number;
}

export interface ProposedMove {
  block: Block;
  toMachineId: string;
  toStartMin: number;
  isFrozen: boolean;
}

interface UndoEntry {
  description: string;
  timestamp: number;
}
const MAX_UNDO = 20;
const RANGE = S1 - S0;
const DRAG_THRESHOLD = 5;

export function useGanttDragDrop(machines: EMachine[], rowHeight: number, ppm: number) {
  const [drag, setDrag] = useState<DragState>({
    isDragging: false,
    block: null,
    offsetX: 0,
    offsetY: 0,
    ghostX: 0,
    ghostY: 0,
  });
  const [proposedMove, setProposedMove] = useState<ProposedMove | null>(null);
  const undoStack = useRef<UndoEntry[]>([]);

  // Pending drag: tracks mousedown before threshold is reached
  const pending = useRef<{
    block: Block;
    startX: number;
    startY: number;
    rect: DOMRect;
  } | null>(null);

  const startDrag = useCallback((block: Block, e: React.MouseEvent) => {
    if (block.freezeStatus === 'frozen') return; // Don't allow drag on frozen blocks
    const el = (e.target as HTMLElement).closest('[data-block-id]');
    const rect = el?.getBoundingClientRect();
    if (!rect) return;
    pending.current = { block, startX: e.clientX, startY: e.clientY, rect };
  }, []);

  // Global listeners for pending drag detection + active drag
  useEffect(() => {
    const handleMove = (e: MouseEvent) => {
      if (pending.current) {
        const dx = e.clientX - pending.current.startX;
        const dy = e.clientY - pending.current.startY;
        if (Math.abs(dx) + Math.abs(dy) >= DRAG_THRESHOLD) {
          const { block, rect } = pending.current;
          setDrag({
            isDragging: true,
            block,
            offsetX: pending.current.startX - rect.left,
            offsetY: pending.current.startY - rect.top,
            ghostX: e.clientX - (pending.current.startX - rect.left),
            ghostY: e.clientY - (pending.current.startY - rect.top),
          });
          pending.current = null;
        }
        return;
      }
      if (!drag.isDragging) return;
      setDrag((d) => ({
        ...d,
        ghostX: e.clientX - d.offsetX,
        ghostY: e.clientY - d.offsetY,
      }));
    };
    const handleUp = () => {
      pending.current = null;
      if (drag.isDragging) {
        // endDrag is called via onMouseUp on the container
      }
    };
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [drag.isDragging]);

  const endDrag = useCallback(
    (containerRect: DOMRect | null) => {
      if (!drag.isDragging || !drag.block || !containerRect) {
        setDrag((d) => ({ ...d, isDragging: false, block: null }));
        return;
      }

      const block = drag.block;
      const relY = drag.ghostY + drag.offsetY - containerRect.top;
      const machineIdx = Math.floor(relY / rowHeight);
      const targetMachine = machines[Math.max(0, Math.min(machineIdx, machines.length - 1))];

      const leftPanelWidth = 100;
      const relX = drag.ghostX + drag.offsetX - containerRect.left - leftPanelWidth;
      const minOffset = relX / ppm;
      const toStartMin = Math.round(S0 + Math.max(0, Math.min(minOffset, RANGE)));

      const isFrozen = block.freezeStatus === 'frozen';

      if (targetMachine.id !== block.machineId || Math.abs(toStartMin - block.startMin) > 5) {
        setProposedMove({ block, toMachineId: targetMachine.id, toStartMin, isFrozen });
      }

      setDrag((d) => ({ ...d, isDragging: false, block: null }));
    },
    [drag, machines, rowHeight, ppm],
  );

  const clearProposal = useCallback(() => setProposedMove(null), []);

  const pushUndo = useCallback((desc: string) => {
    undoStack.current.push({ description: desc, timestamp: Date.now() });
    if (undoStack.current.length > MAX_UNDO) {
      undoStack.current = undoStack.current.slice(-MAX_UNDO);
    }
  }, []);

  const popUndo = useCallback((): UndoEntry | null => {
    return undoStack.current.pop() ?? null;
  }, []);

  return {
    drag,
    proposedMove,
    startDrag,
    endDrag,
    clearProposal,
    pushUndo,
    popUndo,
    undoStackSize: undoStack.current.length,
  };
}
