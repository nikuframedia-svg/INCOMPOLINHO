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
