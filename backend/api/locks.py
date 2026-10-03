"""Shared locks for mutations of the singleton planning state."""

import asyncio
import threading

commit_lock = threading.RLock()


class PlanMutationLock:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        from backend.plans.context import is_staging

        if not is_staging():
            await self._lock.acquire()
        return self

    async def __aexit__(self, *_args):
        from backend.plans.context import is_staging

        if not is_staging():
            self._lock.release()


plan_mutation_lock = PlanMutationLock()
