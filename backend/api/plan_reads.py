"""Analytical reads bound to one captured dataset and plan revision."""

from functools import wraps

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from backend.plans.context import stage_state
from backend.plans.transactions import clone_state
from backend.validation import strict_int


class PlanReadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        @wraps(handler)
        async def captured(request: Request):
            if request.method != "GET":
                return await handler(request)
            from backend.copilot.state import state as default_state

            live = self.endpoint.__globals__.get("state", default_state)
            snapshot = await run_in_threadpool(clone_state, live)
            dataset_id = str((snapshot.dataset_info or {}).get("id", ""))
            revision = int(snapshot.plan_revision)
            expected_dataset = request.headers.get("X-Dataset-Id")
            expected_revision = request.headers.get("X-Plan-Revision")
            try:
                mismatch = (expected_dataset is not None and expected_dataset != dataset_id) or (
                    expected_revision is not None
                    and strict_int(expected_revision, "revision") != revision
                )
            except ValueError:
                mismatch = True
            if mismatch:
                raise HTTPException(
                    409,
                    {
                        "code": "stale_revision",
                        "message": "O plano mudou. Atualiza os dados do ecra.",
                        "dataset_id": dataset_id,
                        "current_revision": revision,
                    },
                )
            with stage_state(live, snapshot):
                response = await handler(request)
            response.headers["X-Dataset-Id"] = dataset_id
            response.headers["X-Plan-Revision"] = str(revision)
            return response

        return captured
