"""Independent small-instance oracle (plano-solver-2026-10-02 §8.2).

Written from the physical rules of AGENTS.md §4, without the project's
allocation helpers. Model: productive window 07:00-24:00 every workday;
one job per machine and per physical tool at a time; a setup is needed
unless the same tool and reference stayed mounted on that machine with no
other use of the tool in between; setups consume the single setup crew of
the machine group; setup and production may be split at the end of a day;
nothing starts before the material release.

``best_schedule`` enumerates every global dispatch order and machine
assignment and list-schedules each job at its earliest feasible time. That
is exact over list schedules, which is a strong reference for 2-4 jobs; it is
not a proof of optimality over all schedules.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

DAY = 1440
OPEN, CLOSE = 420, 1440


@dataclass(frozen=True)
class Job:
    id: str
    tool: str
    reference: str
    machines: tuple[str, ...]
    setup_min: int
    prod_min: int
    release_day: int
    priority: tuple


@dataclass
class Placement:
    job: str
    machine: str
    setup: list[tuple[int, int]] = field(default_factory=list)
    production: list[tuple[int, int]] = field(default_factory=list)

    @property
    def start(self) -> int:
        return self.production[0][0]

    @property
    def finish(self) -> int:
        return self.production[-1][1]


def _pieces(start: int, minutes: int) -> list[tuple[int, int]]:
    """Split ``minutes`` of work from ``start`` across productive windows."""
    pieces, t, left = [], start, minutes
    while left > 0:
        day, offset = divmod(t, DAY)
        if offset < OPEN:
            t = day * DAY + OPEN
            continue
        if offset >= CLOSE:
            t = (day + 1) * DAY + OPEN
            continue
        end = min(day * DAY + CLOSE, t + left)
        pieces.append((t, end))
        left -= end - t
        t = end
    return pieces


def _overlaps(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(s1 < e2 and s2 < e1 for s1, e1 in a for s2, e2 in b)


def _setup_pieces(t: int, minutes: int, split: bool) -> tuple[int, list[tuple[int, int]]]:
    """Setup from ``t``; without ``split`` it must fit in one shift window
    together with the first productive minute (07:00-15:30, 15:30-24:00)."""
    if split or not minutes:
        return t, _pieces(t, minutes)
    while True:
        day, offset = divmod(t, DAY)
        if offset < OPEN:
            t = day * DAY + OPEN
            continue
        if offset >= CLOSE:
            t = (day + 1) * DAY + OPEN
            continue
        window_end = 930 if offset < 930 else CLOSE
        if offset + minutes + 1 <= window_end:
            return t, [(t, t + minutes)]
        t = day * DAY + window_end


def _schedule(order, assignment, jobs, *, split_setup: bool = True) -> list[Placement]:
    machine_free: dict[str, int] = {}
    machine_mount: dict[str, tuple[str, str] | None] = {}
    tool_free: dict[str, int] = {}
    tool_machine: dict[str, str] = {}
    crew: list[tuple[int, int]] = []
    placed = []
    for job_id in order:
        job, machine = jobs[job_id], assignment[job_id]
        mounted = machine_mount.get(machine) == (job.tool, job.reference) and tool_machine.get(
            job.tool) == machine
        setup = 0 if mounted else job.setup_min
        t = max(job.release_day * DAY + OPEN, machine_free.get(machine, 0),
                tool_free.get(job.tool, 0))
        while True:
            t, setup_pieces = _setup_pieces(t, setup, split_setup)
            if not _overlaps(setup_pieces, crew):
                break
            # Advance to the end of the first crew interval in the way.
            t = min(e for s, e in crew if any(s < pe and ps < e for ps, pe in setup_pieces))
        production_start = setup_pieces[-1][1] if setup_pieces else t
        production = _pieces(production_start, job.prod_min)
        placed.append(Placement(job_id, machine, setup_pieces, production))
        crew.extend(setup_pieces)
        machine_free[machine] = production[-1][1]
        tool_free[job.tool] = production[-1][1]
        machine_mount[machine] = (job.tool, job.reference)
        tool_machine[job.tool] = machine
    return placed


def vector(placements: list[Placement], jobs: dict[str, Job]) -> tuple:
    by_job = {p.job: p for p in placements}
    return tuple((job.id, float(by_job[job.id].start), float(by_job[job.id].finish))
                 for job in sorted(jobs.values(), key=lambda j: j.priority))


def best_schedule(
    jobs: dict[str, Job], *, split_setup: bool = True,
) -> tuple[tuple, list[Placement]]:
    """``split_setup=False`` models the current allocator's stricter rule
    that a setup and its first productive minute share one shift window."""
    best = None
    ids = sorted(jobs)
    for order in itertools.permutations(ids):
        for machines in itertools.product(*(jobs[j].machines for j in ids)):
            placements = _schedule(order, dict(zip(ids, machines, strict=True)), jobs,
                                   split_setup=split_setup)
            key = vector(placements, jobs)
            if best is None or key < best[0]:
                best = (key, placements)
    return best


def worst_order_schedule(jobs: dict[str, Job]) -> list[Placement]:
    """A legal but deliberately poor starting plan: reverse priority, first
    eligible machine."""
    order = [job.id for job in sorted(jobs.values(), key=lambda j: j.priority, reverse=True)]
    return _schedule(order, {j: jobs[j].machines[0] for j in jobs}, jobs)


def all_vectors(jobs: dict[str, Job], *, split_setup: bool = True):
    """Anticipation vector of every enumerated list schedule."""
    ids = sorted(jobs)
    for order in itertools.permutations(ids):
        for machines in itertools.product(*(jobs[j].machines for j in ids)):
            yield vector(_schedule(order, dict(zip(ids, machines, strict=True)), jobs,
                                   split_setup=split_setup), jobs)

