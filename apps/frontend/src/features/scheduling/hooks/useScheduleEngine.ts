import { useScheduleComputed } from './useScheduleComputed';
import { useScheduleCore } from './useScheduleCore';

export function useScheduleEngine(initialView = 'plan') {
  const core = useScheduleCore(initialView);
  const computed = useScheduleComputed({
    engineData: core.engineData,
    rushOrders: core.rushOrders,
    mSt: core.mSt,
    appliedReplan: core.appliedReplan,
  });

  return {
    ...core,
    ...computed,
  };
}
