"""Smart scheduling with automatic learning — Spec 08 §7."""

from __future__ import annotations

from backend.scheduler.types import ScheduleResult
from backend.types import EngineData

from .context import extract_context
from .optimizer import OptunaTuner
from .store import LearnStore
from .transfer import ThompsonTransfer


def smart_schedule(
    data: EngineData,
    learn: bool = False,
    label: str = "",
    n_trials: int = 30,
    timeout_s: float = 15.0,
    store_path: str | None = None,
    audit: bool = False,
    config=None,
) -> ScheduleResult:
    """Schedule with automatic learning.

    1. Extract context → find similar ISOPs in history
    2. Use best known params (transfer) or defaults (cold start)
    3. Run schedule_all with those params
    4. If learn=True: re-optimize with Optuna, store result

    Args:
        data: EngineData to schedule.
        learn: If True, run Bayesian optimization and store result.
        label: ISOP label for learning history (e.g. "ISOP_17_3.xlsx").
        n_trials: Optuna trial count (only when learn=True).
        timeout_s: Optuna timeout in seconds (only when learn=True).
        store_path: Path to SQLite DB. None = default (data/learning.db).
        audit: Enable audit trail in schedule_all.

    Returns:
        ScheduleResult with .study attached when learn=True.
    """
    from backend.cpo import optimize

    store = LearnStore(db_path=store_path)
    transfer = ThompsonTransfer(store)
    ctx = extract_context(data, config=config)

    # Get warm-start from history (or None = cold start)
    warm = transfer.suggest_warm_start(ctx)

    if learn:
        tuner = OptunaTuner(data, n_trials=n_trials, timeout_s=timeout_s, config=config)
        study = tuner.optimize(warm_start=warm)

        transfer.record(ctx, study, label)
        store.close()

        result = optimize(data, mode="normal", audit=audit, config=config)
        result.study = study
        return result
    else:
        store.close()
        return optimize(data, mode="quick", audit=audit, config=config)
