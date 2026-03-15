# CP-SAT Solver — Pydantic schemas

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class OperationInput(BaseModel):
    """Uma operação de produção."""

    id: str
    machine_id: str
    tool_id: str
    duration_min: int = Field(..., ge=0, description="Tempo de produção (minutos)")
    setup_min: int = Field(0, ge=0, description="Tempo de setup (minutos)")
    operators: int = Field(1, ge=0)
    calco_code: str | None = None


class JobInput(BaseModel):
    """Um job (encomenda) com operações sequenciais."""

    id: str
    sku: str
    due_date_min: int = Field(..., description="Deadline em minutos absolutos desde t=0")
    weight: float = Field(1.0, ge=0, description="Prioridade/peso do cliente")
    operations: list[OperationInput]


class MachineInput(BaseModel):
    """Uma máquina com capacidade."""

    id: str
    capacity_min: int = Field(
        1020, ge=1, description="Capacidade diária (min, default DAY_CAP=1020)"
    )


class TwinPairInput(BaseModel):
    """Par de peças gémeas que produzem simultaneamente."""

    op_id_a: str
    op_id_b: str
    machine_id: str
    tool_id: str


class ConstraintConfigInput(BaseModel):
    """Activação das 4 constraints Incompol."""

    setup_crew: bool = True
    tool_timeline: bool = True
    calco_timeline: bool = True
    operator_pool: bool = False


class ShiftConfig(BaseModel):
    """Configuração de turnos e capacidade de operadores."""

    shift_x_start: int = Field(420, description="Turno X início (minutos desde 00:00)")
    shift_change: int = Field(930, description="Mudança de turno X→Y (minutos)")
    shift_y_end: int = Field(1440, description="Fim turno Y (minutos)")
    operators_by_machine_shift: dict[str, dict[str, int]] | None = None


class SolverConfig(BaseModel):
    """Configuração do solver."""

    time_limit_s: int = Field(60, ge=1, le=300)
    objective: str = Field(
        "weighted_tardiness",
        pattern="^(makespan|tardiness|weighted_tardiness)$",
    )
    num_workers: int = Field(4, ge=1, le=16)
    use_circuit: bool = Field(
        True,
        description="Use AddCircuit for sequence-dependent setups (zero setup when same tool)",
    )
    objective_mode: str = Field(
        "single",
        pattern="^(single|lexicographic)$",
        description="single: one-phase optimize. lexicographic: 3-phase (tardiness→JIT→setups)",
    )
    warm_start: bool = Field(
        True,
        description="Use EDD heuristic as warm-start seed for CP-SAT",
    )


class SolverRequest(BaseModel):
    """Request para o solver."""

    jobs: list[JobInput]
    machines: list[MachineInput]
    setup_matrix: dict[str, dict[str, int]] | None = None
    config: SolverConfig = Field(default_factory=SolverConfig)
    twin_pairs: list[TwinPairInput] = []
    constraints: ConstraintConfigInput = Field(default_factory=ConstraintConfigInput)
    shifts: ShiftConfig = Field(default_factory=ShiftConfig)

    @model_validator(mode="after")
    def validate_twin_pairs_ops_exist(self) -> SolverRequest:
        """Validate that all op_ids in twin_pairs reference existing operations."""
        if not self.twin_pairs:
            return self
        # Collect all operation IDs from jobs
        all_op_ids: set[str] = set()
        for job in self.jobs:
            for op in job.operations:
                all_op_ids.add(op.id)
        # Check each twin pair
        for pair in self.twin_pairs:
            missing = []
            if pair.op_id_a not in all_op_ids:
                missing.append(pair.op_id_a)
            if pair.op_id_b not in all_op_ids:
                missing.append(pair.op_id_b)
            if missing:
                raise ValueError(f"Twin pair references non-existent op_id(s): {missing}")
        return self


class ScheduledOp(BaseModel):
    """Uma operação agendada na solução."""

    op_id: str
    job_id: str
    machine_id: str
    tool_id: str
    start_min: int
    end_min: int
    setup_min: int
    is_tardy: bool
    tardiness_min: int
    is_twin_production: bool = False
    twin_partner_op_id: str | None = None


class SolverResult(BaseModel):
    """Resultado do solver."""

    schedule: list[ScheduledOp]
    makespan_min: int
    total_tardiness_min: int
    weighted_tardiness: float
    solver_used: str  # cpsat | heuristic
    solve_time_s: float
    status: str  # optimal | feasible | infeasible | timeout
    objective_value: float
    n_ops: int
    operator_warnings: list[dict] = []
    phase_values: dict[str, float] = {}
