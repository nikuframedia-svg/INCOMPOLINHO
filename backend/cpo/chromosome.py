"""Chromosome encoding for CPO v3.0.

Gene groups:
  G1: edd_gap (int [5..30])        — tool_grouping split threshold
  G2: max_edd_span (int [10..50])  — tool_grouping span limit
  G3: machine_choice (dict)        — run_idx → 0=primary/1=alt
  G4: sequence_keys (dict)         — machine → list[float] sort keys
  G5: buffer_pct (float [0..0.30]) — JIT backward buffer
  G6: campaign_window (int [5..30])— campaign sequencing window
"""

from __future__ import annotations

import copy
import hashlib
import pickle
import random
from dataclasses import dataclass, field


# Gene bounds
G1_RANGE = (5, 30)
G2_RANGE = (10, 50)
G5_RANGE = (0.0, 0.30)
G6_RANGE = (5, 30)


@dataclass
class Chromosome:
    edd_gap: int = 10
    max_edd_span: int = 30
    machine_choice: dict[int, int] = field(default_factory=dict)
    sequence_keys: dict[str, list[float]] = field(default_factory=dict)
    buffer_pct: float = 0.05
    campaign_window: int = 15
    crew_priority: list[str] = field(default_factory=list)  # G7: machine priority order for crew
    _hash: str | None = field(default=None, repr=False)

    def compute_hash(self) -> str:
        if self._hash is not None:
            return self._hash
        data = (
            self.edd_gap,
            self.max_edd_span,
            tuple(sorted(self.machine_choice.items())),
            tuple(
                (k, tuple(round(v, 6) for v in vals))
                for k, vals in sorted(self.sequence_keys.items())
            ),
            round(self.buffer_pct, 6),
            self.campaign_window,
            tuple(self.crew_priority),
        )
        self._hash = hashlib.md5(pickle.dumps(data)).hexdigest()
        return self._hash

    def clone(self) -> Chromosome:
        c = Chromosome(
            edd_gap=self.edd_gap,
            max_edd_span=self.max_edd_span,
            machine_choice=dict(self.machine_choice),
            sequence_keys={k: list(v) for k, v in self.sequence_keys.items()},
            buffer_pct=self.buffer_pct,
            campaign_window=self.campaign_window,
            crew_priority=list(self.crew_priority),
        )
        return c

    @staticmethod
    def from_baseline(
        runs: list,
        machine_runs: dict[str, list],
    ) -> Chromosome:
        """Create chromosome encoding the baseline (greedy) schedule.

        Args:
            runs: all ToolRuns (from Phase 2)
            machine_runs: machine_id → list[ToolRun] (from assign_machines)
        """
        # G3: machine_choice — 0=primary, 1=alt for runs with alt
        run_index = {r.id: i for i, r in enumerate(runs)}
        machine_choice: dict[int, int] = {}
        for m_id, m_runs in machine_runs.items():
            for run in m_runs:
                idx = run_index.get(run.id)
                if idx is None:
                    continue
                if run.alt_machine_id is not None:
                    machine_choice[idx] = 0 if m_id == run.machine_id else 1

        # G4: sequence_keys — assign sort keys preserving current order
        sequence_keys: dict[str, list[float]] = {}
        for m_id, m_runs in machine_runs.items():
            sequence_keys[m_id] = [float(i) for i in range(len(m_runs))]

        # G7: crew_priority — order machines by utilisation (heaviest first)
        machine_ids = sorted(machine_runs.keys())
        crew_priority = sorted(machine_ids, key=lambda m: sum(
            r.total_min for r in machine_runs.get(m, [])
        ), reverse=True)

        return Chromosome(
            edd_gap=10,
            max_edd_span=30,
            machine_choice=machine_choice,
            sequence_keys=sequence_keys,
            buffer_pct=0.05,
            campaign_window=15,
            crew_priority=crew_priority,
        )


# ─── Mutation operators ───────────────────────────────────────────────


def mutate_edd_gap(chrom: Chromosome, rng: random.Random) -> Chromosome:
    c = chrom.clone()
    c.edd_gap = _clamp(c.edd_gap + rng.randint(-3, 3), *G1_RANGE)
    return c


def mutate_edd_span(chrom: Chromosome, rng: random.Random) -> Chromosome:
    c = chrom.clone()
    c.max_edd_span = _clamp(c.max_edd_span + rng.randint(-5, 5), *G2_RANGE)
    return c


def mutate_machine(chrom: Chromosome, rng: random.Random) -> Chromosome:
    """Flip one machine assignment (primary ↔ alt)."""
    if not chrom.machine_choice:
        return chrom.clone()
    c = chrom.clone()
    idx = rng.choice(list(c.machine_choice.keys()))
    c.machine_choice[idx] = 1 - c.machine_choice[idx]
    return c


def mutate_sequence_swap(chrom: Chromosome, rng: random.Random) -> Chromosome:
    """Swap two adjacent sort keys in one machine."""
    c = chrom.clone()
    machines = [m for m, keys in c.sequence_keys.items() if len(keys) >= 2]
    if not machines:
        return c
    m = rng.choice(machines)
    keys = c.sequence_keys[m]
    i = rng.randint(0, len(keys) - 2)
    keys[i], keys[i + 1] = keys[i + 1], keys[i]
    return c


def mutate_sequence_insert(chrom: Chromosome, rng: random.Random) -> Chromosome:
    """Relocate one run's sort key to a different position."""
    c = chrom.clone()
    machines = [m for m, keys in c.sequence_keys.items() if len(keys) >= 3]
    if not machines:
        return c
    m = rng.choice(machines)
    keys = c.sequence_keys[m]
    src = rng.randint(0, len(keys) - 1)
    val = keys.pop(src)
    dst = rng.randint(0, len(keys))
    keys.insert(dst, val)
    return c


def mutate_buffer(chrom: Chromosome, rng: random.Random) -> Chromosome:
    c = chrom.clone()
    delta = rng.uniform(-0.05, 0.05)
    c.buffer_pct = _clampf(c.buffer_pct + delta, *G5_RANGE)
    return c


def mutate_campaign(chrom: Chromosome, rng: random.Random) -> Chromosome:
    c = chrom.clone()
    c.campaign_window = _clamp(c.campaign_window + rng.randint(-3, 3), *G6_RANGE)
    return c


def mutate_crew_priority(chrom: Chromosome, rng: random.Random) -> Chromosome:
    """Swap two adjacent machines in crew priority order."""
    c = chrom.clone()
    if len(c.crew_priority) < 2:
        return c
    i = rng.randint(0, len(c.crew_priority) - 2)
    c.crew_priority[i], c.crew_priority[i + 1] = (
        c.crew_priority[i + 1], c.crew_priority[i]
    )
    return c


def mutate_strong(chrom: Chromosome, rng: random.Random) -> Chromosome:
    """Strong shake: randomize 3-5 genes."""
    c = chrom.clone()
    n = rng.randint(3, 5)
    ops = [mutate_edd_gap, mutate_edd_span, mutate_machine,
           mutate_sequence_swap, mutate_buffer, mutate_campaign,
           mutate_crew_priority]
    for op in rng.sample(ops, min(n, len(ops))):
        c = op(c, rng)
    return c


def crossover_uniform(a: Chromosome, b: Chromosome, rng: random.Random) -> Chromosome:
    """Uniform crossover: 50/50 per gene group."""
    c = a.clone()
    if rng.random() < 0.5:
        c.edd_gap = b.edd_gap
    if rng.random() < 0.5:
        c.max_edd_span = b.max_edd_span
    if rng.random() < 0.5:
        c.machine_choice = dict(b.machine_choice)
    if rng.random() < 0.5:
        c.buffer_pct = b.buffer_pct
    if rng.random() < 0.5:
        c.campaign_window = b.campaign_window
    if rng.random() < 0.5 and b.crew_priority:
        c.crew_priority = list(b.crew_priority)
    # Sequence: per-machine 50/50
    for m_id in set(list(a.sequence_keys) + list(b.sequence_keys)):
        if rng.random() < 0.5 and m_id in b.sequence_keys:
            c.sequence_keys[m_id] = list(b.sequence_keys[m_id])
    return c


# All operators (name → callable)
OPERATORS: dict[str, callable] = {
    "mutate_edd_gap": mutate_edd_gap,
    "mutate_edd_span": mutate_edd_span,
    "mutate_machine": mutate_machine,
    "mutate_seq_swap": mutate_sequence_swap,
    "mutate_seq_insert": mutate_sequence_insert,
    "mutate_buffer": mutate_buffer,
    "mutate_campaign": mutate_campaign,
    "mutate_crew_priority": mutate_crew_priority,
    "mutate_strong": mutate_strong,
}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _clampf(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
