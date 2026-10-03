import type { CurrentMachineState } from "../api/types";

export function currentStateForStatus(
  current: CurrentMachineState,
  status: CurrentMachineState["status"],
): CurrentMachineState {
  const next: CurrentMachineState = {
    machine_id: current.machine_id,
    status,
    note: current.note ?? "",
  };

  if (status === "producing") {
    next.sku = current.sku;
    next.tool_id = current.tool_id;
    next.remaining_qty = current.remaining_qty;
    next.expected_end = current.expected_end;
  } else if (status === "setup" || status === "trial") {
    next.tool_id = current.tool_id;
    next.expected_end = current.expected_end;
  } else if (status === "down") {
    next.expected_end = current.expected_end;
  }

  return next;
}

export function isCurrentStateReady(item: CurrentMachineState | undefined): boolean {
  if (!item) return false;
  if (item.status === "producing") {
    return Boolean(
      item.sku
      && item.tool_id
      && item.remaining_qty
      && item.remaining_qty > 0
      && item.expected_end,
    );
  }
  if (item.status === "setup" || item.status === "trial") {
    return Boolean(item.tool_id && item.expected_end);
  }
  return true;
}
