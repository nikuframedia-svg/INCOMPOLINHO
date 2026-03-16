# CP-SAT Solver — Pydantic schemas


from pydantic import BaseModel, Field


class OperationInput(BaseModel):
    """Uma operação de produção."""

    id: str
    machine_id: str
    tool_id: str
    duration_min: int = Field(..., ge=0, description="Tempo de produção (minutos)")
    setup_min: int = Field(0, ge=0, description="Tempo de setup (minutos)")
    operators: int = Field(1, ge=0)


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


class SolverConfig(BaseModel):
    """Configuração do solver."""

    time_limit_s: int = Field(60, ge=1, le=300)
    objective: str = Field(
        "weighted_tardiness",
        pattern="^(makespan|tardiness|weighted_tardiness)$",
    )
    num_workers: int = Field(4, ge=1, le=16)


class SolverRequest(BaseModel):
    """Request para o solver."""

    jobs: list[JobInput]
    machines: list[MachineInput]
    setup_matrix: dict[str, dict[str, int]] | None = None
    config: SolverConfig = Field(default_factory=SolverConfig)


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
