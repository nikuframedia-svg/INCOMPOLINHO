"""Worker-local staging for the existing state-based planning services."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MutationContext:
    original: object
    staged: object
    validators: list[Callable] = field(default_factory=list)
    callbacks: list[Callable] = field(default_factory=list)
    api_write: bool = False
    recalculate_from_start: bool = False
    approval_required: object | None = None
    approval_action: str = "recompute"
    # The instant this write was calculated at (AGENTS §2 rule 4): the commit
    # guard reads today's history at it. A write that applies a candidate
    # calculated earlier (a replan job, a manual move) sets that one.
    planning_now: datetime | None = None
    # What this write changed, in pt-PT, for the version history (decisão de
    # 15/10/2026): the name of the committed snapshot. An endpoint sets the
    # explicit label; ``update_schedule``/``persist_current_plan`` leave a
    # default; ``history.snapshot_name`` picks the best at commit.
    change_label: str | None = None
    default_label: str | None = None
    change_kind: str = ""
    # «Desfazer»: the snapshot being put back; the new one takes its place in
    # the chain (its own «Desfazer» goes further back, never forward).
    undo_restores: str | None = None
    # «Mover lote» of a lot that, by the plan, had only started today: the
    # server's own signal that it was not produced (decisão do Luís,
    # 21/10/2026), read by the commit guard (``frozen._unproduced_today``).
    unproduced_lot: str | None = None


_context: ContextVar[MutationContext | None] = ContextVar("plan_mutation", default=None)


def redirected_state(instance):
    context = _context.get()
    return context.staged if context is not None and instance is context.original else None


def is_staging() -> bool:
    return _context.get() is not None


def recalculation_from_start() -> bool:
    context = _context.get()
    return context is not None and context.recalculate_from_start


def set_planning_now(now: datetime | str | None) -> None:
    """Record the instant the candidate being written was calculated at."""
    context = _context.get()
    if context is None or not now:
        return
    context.planning_now = datetime.fromisoformat(now) if isinstance(now, str) else now


def set_change_label(
    label: str, *, kind: str = "", undo_restores: str | None = None,
    unproduced: str | None = None,
) -> None:
    """Name the change this write makes (the snapshot name in «Planos»).

    ``unproduced``: the lot a «Mover lote» says was not produced today; set
    only by ``manual_plan.apply_move`` from its own checked candidate.
    """
    context = _context.get()
    if context is None or not label:
        return
    context.change_label = str(label)
    if kind:
        context.change_kind = kind
    if undo_restores:
        context.undo_restores = undo_restores
    if unproduced:
        context.unproduced_lot = str(unproduced)


def set_default_change_label(label: str | None) -> None:
    """A fallback name, used only when no endpoint named the change."""
    context = _context.get()
    if context is not None and label:
        context.default_label = str(label)


def change_history(context: MutationContext | None) -> dict:
    """The history fields of a write, detached from the live context."""
    if context is None:
        return {}
    return {
        "label": context.change_label,
        "default_label": context.default_label,
        "kind": context.change_kind,
        "undo_restores": context.undo_restores,
        "unproduced": context.unproduced_lot,
    }


def api_write_context() -> MutationContext | None:
    context = _context.get()
    return context if context is not None and context.api_write else None


def after_commit(callback: Callable) -> None:
    context = _context.get()
    if context is None:
        callback()
    else:
        context.callbacks.append(callback)


def before_commit(callback: Callable) -> None:
    context = _context.get()
    if context is None:
        callback()
    else:
        context.validators.append(callback)


@contextmanager
def stage_state(original, staged):
    context = MutationContext(original, staged)
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)
