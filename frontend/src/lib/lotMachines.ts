import type { Lot } from "../api/types";

/**
 * Machines the lot may be moved to: the machines of its tool, primary first,
 * as the server reads them from the operations (`eligible_machines`). The
 * lot's own pair is only the fallback (an older server): a lot an earlier
 * calculation put on its alternative may carry alternative/alternative and
 * must still be able to go back to its primary (E13, 23/10/2026).
 */
export function lotEligibleMachines(lot: Pick<Lot, "machine_id" | "alt_machine_id" | "eligible_machines">): string[] {
  const machines = lot.eligible_machines?.length
    ? lot.eligible_machines
    : [lot.machine_id, lot.alt_machine_id];
  return [...new Set(machines.filter((id): id is string => Boolean(id)))];
}
