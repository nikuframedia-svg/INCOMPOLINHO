"""Optional phase observations for long calculations, local to one worker.

Durations are inclusive: construction can contain normalization/validation.
This observes the existing algorithm; it does not change solver time budgets.
Phase boundaries honor an explicitly installed cooperative planning control.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from backend.planning_control import planning_checkpoint

PhaseObserver = Callable[[str, str, float], None]
_observer: ContextVar[PhaseObserver | None] = ContextVar("phase_observer", default=None)


@contextmanager
def observe_phases(observer: PhaseObserver):
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


@contextmanager
def phase(name: str):
    planning_checkpoint()
    observer = _observer.get()
    if observer is None:
        yield
        planning_checkpoint()
        return
    observer(name, "start", 0.0)
    started = time.perf_counter()
    try:
        yield
        planning_checkpoint()
    finally:
        observer(name, "end", (time.perf_counter() - started) * 1000)


def measured(name: str):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with phase(name):
                return fn(*args, **kwargs)

        return wrapped

    return decorate
