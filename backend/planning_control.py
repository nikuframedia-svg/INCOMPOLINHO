"""Cooperative planning limits, scoped to the current worker's call tree.

No scope means no deadline. A nested scope can tighten, never relax, its
parent's limits. Worker/thread entry points must establish their own scope.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from typing import Protocol


class CancellationEvent(Protocol):
    def is_set(self) -> bool: ...


class PlanningStopped(Exception):
    """The candidate is incomplete and must not replace the active plan."""


class PlanningTimeout(PlanningStopped, TimeoutError):
    """The total planning budget has expired."""


class PlanningCancelled(PlanningStopped):
    """The caller cancelled planning."""


@dataclass(frozen=True)
class PlanningControl:
    deadline: float | None = None
    cancel_event: CancellationEvent | None = None
    clock: Callable[[], float] = time.monotonic
    cancelled: Callable[[], bool] | None = None
    parent: PlanningControl | None = None
    cache: dict = field(default_factory=dict, compare=False)

    def checkpoint(self) -> None:
        # Cancellation wins over timeout when both occur together.
        current = self
        while current is not None:
            if (current.cancel_event is not None and current.cancel_event.is_set()) or (
                current.cancelled is not None and current.cancelled()
            ):
                raise PlanningCancelled("Planning cancelled; candidate not committed.")
            current = current.parent
        current = self
        while current is not None:
            if current.deadline is not None and current.clock() >= current.deadline:
                raise PlanningTimeout("Planning deadline expired; candidate not committed.")
            current = current.parent

    def remaining(self) -> float | None:
        self.checkpoint()
        limits = []
        current = self
        while current is not None:
            if current.deadline is not None:
                limits.append(max(0.0, current.deadline - current.clock()))
            current = current.parent
        return min(limits) if limits else None


_control: ContextVar[PlanningControl | None] = ContextVar("planning_control", default=None)
_candidate_observer: ContextVar[Callable | None] = ContextVar("candidate_observer", default=None)

# Process-wide count of open top-level planning scopes. Background analyses
# (robustness) yield the CPU while it is non-zero so they never compete with,
# and therefore never influence, a time-limited plan search.
_active_planning = 0
_active_planning_lock = Lock()


def planning_active() -> bool:
    """True while any thread runs a top-level planning scope."""
    return _active_planning > 0


def wait_while_planning(
    cancelled: Callable[[], bool] | None = None,
    *,
    interval_s: float = 0.05,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Block a background worker while planning runs; False when cancelled first."""
    while planning_active():
        if cancelled is not None and cancelled():
            return False
        sleep(interval_s)
    return not (cancelled is not None and cancelled())


def _track_planning(delta: int) -> None:
    global _active_planning
    with _active_planning_lock:
        _active_planning = max(0, _active_planning + delta)


@contextmanager
def candidate_observer(callback, *, forward=False):
    """Notify owners unless a nested retainer explicitly rejects the candidate."""
    parent = _candidate_observer.get()

    def dispatch(result):
        accepted = callback(result)
        if accepted is not False and forward and parent is not None:
            parent(result)

    token = _candidate_observer.set(dispatch)
    try:
        yield
    finally:
        _candidate_observer.reset(token)


def candidate_completed(result) -> None:
    callback = _candidate_observer.get()
    if callback is not None:
        callback(result)


def current_planning_control() -> PlanningControl | None:
    return _control.get()


@contextmanager
def planning_scope(
    *,
    timeout_s: float | None = None,
    cancel_event: CancellationEvent | None = None,
    cancelled: Callable[[], bool] | None = None,
    clock: Callable[[], float] | None = None,
    check_on_exit: bool = True,
    background: bool = False,
):
    """Bound nested work; durable writers check explicitly before commit instead of at exit.

    A top-level scope counts as active planning unless ``background`` is set
    (informational analyses that must yield to planning, never count as it).
    """
    parent = _control.get()
    tracked = parent is None and not background
    clock = clock or (parent.clock if parent is not None else time.monotonic)
    control = PlanningControl(
        deadline=None if timeout_s is None else clock() + max(0.0, timeout_s),
        cancel_event=cancel_event,
        clock=clock,
        cancelled=cancelled,
        parent=parent,
        cache=parent.cache if parent is not None else {},
    )
    token = _control.set(control)
    if tracked:
        _track_planning(1)
    try:
        control.checkpoint()
        yield control
        if check_on_exit:
            control.checkpoint()
    finally:
        if tracked:
            _track_planning(-1)
        _control.reset(token)


def planning_checkpoint() -> None:
    control = _control.get()
    if control is not None:
        control.checkpoint()


def remaining_time(limit_s: float | None = None) -> float | None:
    control = _control.get()
    remaining = None if control is None else control.remaining()
    if remaining is None:
        return limit_s
    return remaining if limit_s is None else min(limit_s, remaining)


def closing_reserve(budget: float) -> float:
    return min(10.0, max(0.0, budget) * 0.2)


def improvement_time_budget(total_budget_s: float) -> float:
    """Use remaining request time, never the validation/commit reserve."""
    return max(0.0, remaining_time(total_budget_s) - closing_reserve(total_budget_s))


def improvement_reserve(total_budget_s: float) -> float:
    """After a complete candidate, protect time from advisory re-solves.

    Keep most remaining search time for the shared no-loss neighbourhoods;
    any time the advisory search does not use is available to them too.
    """
    return min(max(0.0, total_budget_s) * 0.5,
               improvement_time_budget(total_budget_s) * 0.75)


def execution_cache(namespace: str) -> dict:
    """Caches never survive the outer calculation or cross worker contexts."""
    control = current_planning_control()
    return {} if control is None else control.cache.setdefault(namespace, {})


def solve_cpsat(solver, model):
    """Stop native search even before its first solution; always join the watcher.

    Repeated stop requests cover the race where cancellation arrives before
    CP-SAT installs its native solve wrapper. Local solver budgets remain intact.
    """
    control = _control.get()
    if control is None:
        return solver.solve(model)
    remaining = control.remaining()
    if remaining is not None:
        solver.parameters.max_time_in_seconds = min(
            solver.parameters.max_time_in_seconds, remaining
        )
    done = Event()
    stopped: list[PlanningStopped] = []

    def watch() -> None:
        while not done.wait(0.02):
            try:
                control.checkpoint()
            except PlanningStopped as exc:
                if not stopped:
                    stopped.append(exc)
                solver.stop_search()

    watcher = Thread(target=watch, name="planning-cpsat-watchdog", daemon=True)
    watcher.start()
    try:
        control.checkpoint()
        status = solver.solve(model)
    finally:
        done.set()
        watcher.join()
    if stopped:
        raise stopped[0]
    control.checkpoint()
    return status
