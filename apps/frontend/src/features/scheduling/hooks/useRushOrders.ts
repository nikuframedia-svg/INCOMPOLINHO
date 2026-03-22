/**
 * useRushOrders — Rush order insertion logic.
 */

import { useCallback, useState } from 'react';
import type { EOp } from '@/domain/types/scheduling';
import { useToastStore } from '../../../stores/useToastStore';

export interface RushOrderState {
  roTool: string;
  roQty: number;
  roDeadline: number;
}

export interface RushOrderActions {
  setRoTool: React.Dispatch<React.SetStateAction<string>>;
  setRoQty: React.Dispatch<React.SetStateAction<number>>;
  setRoDeadline: React.Dispatch<React.SetStateAction<number>>;
  addRushOrder: () => void;
  removeRushOrder: (idx: number) => void;
}

export function useRushOrders(
  ops: EOp[],
  wdi: number[],
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >,
): { state: RushOrderState; actions: RushOrderActions } {
  const [roTool, setRoTool] = useState('');
  const [roQty, setRoQty] = useState(500);
  const [roDeadline, setRoDeadline] = useState(() => wdi[2] ?? 2);

  const addRushOrder = useCallback(() => {
    if (!roTool) return;
    const matchOp = ops.find((o) => o.t === roTool);
    const sku = matchOp?.sku ?? roTool;
    setRushOrders((prev) => [...prev, { toolId: roTool, sku, qty: roQty, deadline: roDeadline }]);
    setRoTool('');
    useToastStore
      .getState()
      .actions.addToast(`Rush order adicionada: ${roTool} · ${roQty} pcs`, 'success', 3000);
  }, [roTool, roQty, roDeadline, ops, setRushOrders]);

  const removeRushOrder = useCallback(
    (idx: number) => {
      setRushOrders((prev) => prev.filter((_, i) => i !== idx));
    },
    [setRushOrders],
  );

  return {
    state: { roTool, roQty, roDeadline },
    actions: { setRoTool, setRoQty, setRoDeadline, addRushOrder, removeRushOrder },
  };
}
